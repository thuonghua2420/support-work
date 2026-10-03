from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .app_config import AppConfig, load_app_config
from .compare_keys import extract_all_compare_keys, remove_compare_keys
from .compare_workbook_view import (
    CompareWorkbookReference,
    build_compare_view_index,
    read_compare_sheet,
    scan_compare_workbook_fixmes,
)
from .database_io import (
    DatabaseConnectionSettings,
    OperationCancelledError,
    database_type_options,
    database_label,
    default_port,
    default_schema,
    export_csv_folder,
    get_available_sqlserver_drivers,
    import_csv_folder,
    is_modern_sqlserver_odbc_driver,
    list_database_names,
    list_database_tables,
    normalize_csv_folder,
    preferred_sqlserver_driver,
    scan_import_csv_tables,
    sync_database_tables,
    test_database_connection,
)
from .excel_image_formatter import format_excel_workbooks
from .excel_compare import compare_excel_workbooks
from .pdf_compare import compare_pdf_files
from .image_compare import compare_images
from .excel_format_presets import ExcelFormatPreset, ExcelFormatPresetStore
from .excel_writer import WorkbookFixmeEntry
from .file_utilities import (
    delete_contains_text,
    delete_empty_folders,
    find_empty_folders,
    move_files_contains_text,
    rename_contains_text,
    rename_exact_name,
    rename_excel_sheets_contains,
)
from .fixme_notes import FixmeNote, FixmeNoteStore
from .fixme_replacements import apply_fixme_replacements
from .folder_compare import (
    compare_csv_folder_pairs,
    compare_csv_folder_pairs_to_workbook,
    compare_csv_folders,
    preview_folder_compare_pairs,
)
from .processor import process_root
from .sql_excel_loader import format_excel_sql_entries, load_sql_entries_from_excel, render_raw_sql_entries
from .sql_tools import analyze_sql, format_sql
from .sql_database_workspace import SqlDatabaseWorkspaceManager

APP_TITLE = "AutoCompare"
BUILD_MARKER = "DBFIX-20260927-01"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DB_CONNECTION_HISTORY_LIMIT = 50
DB_CONNECTION_HISTORY_FILE = "database_connection_history.json"
STATIC_DIR = Path(__file__).resolve().parent / "web"
Logger = Callable[[str], None]


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def throw_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelledError("Tác vụ đã được hủy bởi người dùng.")


@dataclass
class WebJob:
    id: str
    action: str
    label: str
    cancel_token: CancelToken = field(repr=False)
    state: str = "queued"
    status: str = "Đang chờ..."
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: _now_iso())
    started_at: str | None = None
    finished_at: str | None = None

    def snapshot(self, cursor: int = 0) -> dict[str, Any]:
        safe_cursor = min(max(cursor, 0), len(self.logs))
        return {
            "id": self.id,
            "action": self.action,
            "label": self.label,
            "state": self.state,
            "status": self.status,
            "logs": self.logs[safe_cursor:],
            "next_cursor": len(self.logs),
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_token.cancelled,
        }


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: WebJob | None = None

    def start(
        self,
        action: str,
        label: str,
        operation: Callable[[Logger, CancelToken], dict[str, Any]],
    ) -> WebJob:
        with self._lock:
            if self._current is not None and self._current.state in {"queued", "running"}:
                raise RuntimeError("Một tác vụ khác đang chạy. Vui lòng chờ tác vụ hiện tại hoàn tất.")
            job = WebJob(id=uuid.uuid4().hex, action=action, label=label, cancel_token=CancelToken(), status=label)
            self._current = job

        worker = threading.Thread(target=self._run, args=(job, operation), daemon=True)
        worker.start()
        return job

    def snapshot(self, cursor: int = 0) -> dict[str, Any] | None:
        with self._lock:
            if self._current is None:
                return None
            return self._current.snapshot(cursor)

    def cancel_current(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            if self._current is None or self._current.state not in {"queued", "running"}:
                return {"cancel_requested": False, "state": "idle"}
            if job_id and self._current.id != job_id:
                raise ValueError("Tác vụ cần hủy không còn là tác vụ đang chạy.")
            self._current.cancel_token.cancel()
            self._current.status = "Đang hủy tác vụ..."
            self._current.logs.append("Đã gửi yêu cầu hủy. Hệ thống sẽ dừng tại điểm an toàn gần nhất.")
            return {"cancel_requested": True, "job": self._current.snapshot()}

    def _run(self, job: WebJob, operation: Callable[[Logger, CancelToken], dict[str, Any]]) -> None:
        with self._lock:
            job.state = "running"
            job.started_at = _now_iso()

        def log(message: str) -> None:
            with self._lock:
                job.logs.append(str(message))

        try:
            job.cancel_token.throw_if_cancelled()
            result = operation(log, job.cancel_token)
        except OperationCancelledError as exc:
            with self._lock:
                job.state = "cancelled"
                job.status = "Đã hủy"
                job.error = str(exc)
                job.logs.append(str(exc))
                job.finished_at = _now_iso()
            return
        except Exception as exc:
            with self._lock:
                job.state = "failed"
                job.status = "Tác vụ thất bại"
                job.error = str(exc)
                job.logs.append(f"LỖI: {exc}")
                job.finished_at = _now_iso()
            return

        with self._lock:
            job.state = "succeeded"
            job.status = "Hoàn tất"
            job.result = result
            job.finished_at = _now_iso()


class AutoCompareWebApplication:
    ACTION_LABELS = {
        "compare_keys_extract": "Đang trích xuất primary key...",
        "compare_keys_remove": "Đang xóa key compare đã lưu...",
        "compare": "Đang chạy so sánh UT...",
        "folder_compare": "Đang so sánh hai folder CSV...",
        "excel_compare": "Đang so sánh hai file Excel...",
        "pdf_compare": "Đang so sánh hai file PDF...",
        "format_excel_workbooks": "Đang định dạng workbook Excel...",
        "sql_format": "Đang format câu SQL...",
        "sql_analyze": "Đang phân tích toàn bộ câu SQL...",
        "sql_load_excel": "Đang đọc và format SQL từ Excel...",
        "rename_exact": "Đang đổi tên chính xác...",
        "rename_contains": "Đang đổi tên theo nội dung...",
        "delete_contains": "Đang xóa file/folder...",
        "rename_sheets": "Đang đổi tên sheet Excel...",
        "move_files": "Đang di chuyển file...",
        "find_empty_folders": "Đang kiểm tra folder trống...",
        "delete_empty_folders": "Đang xóa folder trống...",
        "db_test": "Đang kiểm tra kết nối CSDL...",
        "db_list_databases": "Đang tải danh sách CSDL...",
        "db_list_tables": "Đang tải danh sách table...",
        "db_normalize": "Đang chuẩn hóa CSV...",
        "db_scan_csv": "Đang quét file CSV...",
        "db_import": "Đang nhập CSV vào CSDL...",
        "db_export": "Đang xuất CSDL ra CSV...",
        "db_sync": "Đang đồng bộ hai CSDL...",
        "apply_fixmes": "Đang áp dụng ghi chú FIXME...",
        "check_fixmes": "Đang kiểm tra FIXME còn lại...",
    }
    CONFIRMED_ACTIONS = {
        "compare_keys_remove",
        "delete_contains",
        "delete_empty_folders",
        "db_import",
        "db_export",
        "db_sync",
        "format_excel_workbooks",
    }

    def __init__(self) -> None:
        self.config: AppConfig = load_app_config()
        self.note_store = FixmeNoteStore()
        self.excel_format_preset_store = ExcelFormatPresetStore()
        self.sql_workspace = SqlDatabaseWorkspaceManager(self.config.database_workspace)
        self.jobs = JobManager()
        self._state_lock = threading.Lock()
        self._fixme_entries: list[WorkbookFixmeEntry] = []
        self._compare_workbooks: list[CompareWorkbookReference] = []
        self._db_connection_cache: dict[str, DatabaseConnectionSettings] = {}
        self._db_connection_history: dict[str, DatabaseConnectionSettings] = _load_db_connection_history()
        self._db_table_cache: dict[str, list[str]] = {}

    def bootstrap(self, port: int) -> dict[str, Any]:
        notes = self.note_store.load()
        excel_format_presets = self.excel_format_preset_store.load()
        return {
            "app_title": APP_TITLE,
            "build_marker": BUILD_MARKER,
            "cwd": str(Path.cwd()),
            "port": port,
            "compare_workflows": [
                {
                    "key": workflow.key,
                    "label": workflow.label,
                    "default_enabled": workflow.default_enabled,
                }
                for workflow in self.config.compare_workflows
            ],
            "folder_compare_file": self.config.workbooks.folder_compare_file,
            "compare_options": {
                "copy_input": self.config.copy_input_default,
                "sort_by_key": self.config.sort_by_key_default,
            },
            "update_compare_keys": load_app_config().update_compare_keys,
            "database_types": database_type_options(),
            "database_defaults": {
                database_type: {
                    "port": default_port(database_type),
                    "schema": default_schema(database_type),
                }
                for database_type in database_type_options()
            },
            "database_workspace": asdict(self.config.database_workspace),
            "sqlserver_drivers": get_available_sqlserver_drivers(),
            "database_connections": self._public_database_connection_cache(),
            "database_connection_history": self._public_database_connection_history(),
            "database_tables": self._public_database_table_cache(),
            "notes": [_note_to_dict(note) for note in notes],
            "excel_format_presets": [_excel_format_preset_to_dict(item) for item in excel_format_presets],
            "fixmes": self.fixme_snapshot(),
            "compare_view": self.compare_view_index(),
            "job": self.jobs.snapshot(),
        }

    def fixme_snapshot(self) -> list[dict[str, Any]]:
        with self._state_lock:
            return [_fixme_to_dict(entry, index) for index, entry in enumerate(self._fixme_entries)]

    def compare_view_index(self) -> dict[str, Any]:
        with self._state_lock:
            workbooks = list(self._compare_workbooks)
        return build_compare_view_index(workbooks)

    def compare_sheet_snapshot(self, workbook_id: str, sheet_name: str) -> dict[str, Any]:
        try:
            index = int(workbook_id)
        except ValueError as exc:
            raise ValueError("Workbook compare không hợp lệ.") from exc
        with self._state_lock:
            workbooks = list(self._compare_workbooks)
            fixme_entries = list(self._fixme_entries)
        if index < 0 or index >= len(workbooks):
            raise ValueError("Workbook compare không tồn tại trong lần so sánh hiện tại.")
        return read_compare_sheet(workbooks[index], sheet_name, fixme_entries)

    def _public_database_connection_cache(self) -> dict[str, dict[str, Any]]:
        with self._state_lock:
            return {
                scope: _public_db_settings(settings)
                for scope, settings in self._db_connection_cache.items()
            }

    def _public_database_connection_history(self) -> list[dict[str, Any]]:
        with self._state_lock:
            return [
                _public_db_settings(settings)
                for settings in reversed(list(self._db_connection_history.values()))
            ]

    def _public_database_table_cache(self) -> dict[str, list[str]]:
        with self._state_lock:
            return {scope: list(tables) for scope, tables in self._db_table_cache.items()}

    def _remember_db_connection_history_unlocked(self, settings: DatabaseConnectionSettings) -> None:
        key = _db_connection_history_key(settings)
        if key in self._db_connection_history:
            del self._db_connection_history[key]
        self._db_connection_history[key] = settings
        while len(self._db_connection_history) > DB_CONNECTION_HISTORY_LIMIT:
            oldest_key = next(iter(self._db_connection_history))
            del self._db_connection_history[oldest_key]
        _save_db_connection_history(list(self._db_connection_history.values()))

    def _remember_db_connection_history(self, settings: DatabaseConnectionSettings) -> None:
        validated = _db_settings(asdict(settings))
        with self._state_lock:
            self._remember_db_connection_history_unlocked(validated)

    def _remember_db_connection(
        self,
        role: str,
        settings: DatabaseConnectionSettings,
        tables: list[str] | None = None,
    ) -> None:
        role = str(role or "main")
        validated = _db_settings(asdict(settings))
        with self._state_lock:
            self._db_connection_cache[role] = validated
            self._remember_db_connection_history_unlocked(validated)
            if tables is not None:
                self._db_table_cache[role] = list(tables)

    def _db_settings_for_role(self, raw_settings: Any, role: str) -> DatabaseConnectionSettings:
        settings = _db_settings(raw_settings)
        role = str(role or "main")
        if settings.password:
            return settings
        with self._state_lock:
            cached = self._db_connection_cache.get(role)
            history = list(self._db_connection_history.values())
        if cached is not None and _db_settings_match_except_password(settings, cached):
            return replace(settings, password=cached.password)
        for previous in reversed(history):
            if _db_settings_match_except_password(settings, previous):
                return replace(settings, password=previous.password)
        for previous in reversed(history):
            if _db_settings_match_server_login_except_password(settings, previous):
                return replace(settings, password=previous.password)
        return settings

    def enable_sql_write_mode(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise PermissionError("Cần xác nhận trên giao diện trước khi chạy CUD/DDL.")
        return self.sql_workspace.enable_write_mode(self._db_settings_for_role(payload.get("settings"), "main"))

    def inspect_sql_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.sql_workspace.inspect_execution(
            _text(payload, "sql"),
            self._db_settings_for_role(payload.get("settings"), "main"),
            run_mode=str(payload.get("run_mode", "all")),
        )

    def switch_database_session_cache(self) -> dict[str, Any]:
        with self._state_lock:
            self._db_connection_cache["main"], self._db_connection_cache["target"] = (
                self._db_connection_cache.get("target"),
                self._db_connection_cache.get("main"),
            )
            self._db_connection_cache = {
                scope: settings
                for scope, settings in self._db_connection_cache.items()
                if settings is not None
            }
            self._db_table_cache["main"], self._db_table_cache["target"] = (
                self._db_table_cache.get("target", []),
                self._db_table_cache.get("main", []),
            )
            self._db_table_cache = {
                scope: list(tables)
                for scope, tables in self._db_table_cache.items()
                if tables
            }
        return {
            "database_connections": self._public_database_connection_cache(),
            "database_connection_history": self._public_database_connection_history(),
            "database_tables": self._public_database_table_cache(),
        }

    def save_note(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        value = _text(payload, "value")
        meaning = str(payload.get("meaning", "")).strip()
        old_value = str(payload.get("old_value", "")).strip()
        if old_value:
            notes = self.note_store.replace(old_value, value, meaning)
        else:
            notes = self.note_store.upsert(value, meaning)
        return [_note_to_dict(note) for note in notes]

    def delete_note(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        notes = self.note_store.delete(_text(payload, "value"))
        return [_note_to_dict(note) for note in notes]

    def save_excel_format_preset(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        presets = self.excel_format_preset_store.upsert(
            name=_text(payload, "name"),
            font_name=_text(payload, "font_name"),
            font_size=payload.get("font_size", 11),
            exclusions=payload.get("exclusions", ""),
        )
        return [_excel_format_preset_to_dict(item) for item in presets]

    def delete_excel_format_preset(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        presets = self.excel_format_preset_store.delete(_text(payload, "name"))
        return [_excel_format_preset_to_dict(item) for item in presets]

    def preview_folder_compare_pairs(self, payload: dict[str, Any]) -> dict[str, Any]:
        pairs = preview_folder_compare_pairs(_text(payload, "left"), _text(payload, "right"))
        return {
            "pairs": [
                {"left_name": pair.left_name, "right_name": pair.right_name, "output_name": pair.output_name}
                for pair in pairs
            ]
        }

    def start_action(self, action: str, payload: dict[str, Any]) -> WebJob:
        extra_labels = {
            "db_sql_execute": "Dang chay SQL Workspace...",
            "db_sql_export": "Dang export source data SQL...",
            "db_sql_update": "Dang update data tu SQL grid...",
        }
        action_labels = {**self.ACTION_LABELS, **extra_labels}
        confirmed_actions = set(self.CONFIRMED_ACTIONS) | {"db_sql_export", "db_sql_update"}
        if action not in action_labels:
            raise ValueError(f"Tác vụ không được hỗ trợ: {action}")
        if action in confirmed_actions and payload.get("confirmed") is not True:
            raise PermissionError("Tác vụ này cần được xác nhận rõ ràng trước khi chạy.")
        operation = self._operation(action, payload)
        return self.jobs.start(action, action_labels[action], operation)

    def list_files(self, path_value: str, kind: str, extensions: list[str]) -> dict[str, Any]:
        requested = Path(path_value).expanduser() if path_value else Path.cwd()
        try:
            current = requested.resolve()
        except OSError:
            current = Path.cwd().resolve()
        if current.is_file():
            current = current.parent
        if not current.exists() or not current.is_dir():
            raise FileNotFoundError(f"Folder không tồn tại: {current}")

        normalized_extensions = {
            item.lower() if item.startswith(".") else f".{item.lower()}"
            for item in extensions
            if item.strip()
        }
        entries: list[dict[str, Any]] = []
        try:
            children = sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except PermissionError as exc:
            raise PermissionError(f"Không có quyền đọc folder: {current}") from exc

        for child in children:
            try:
                is_dir = child.is_dir()
                if kind == "directory" and not is_dir:
                    continue
                if not is_dir and normalized_extensions and child.suffix.lower() not in normalized_extensions:
                    continue
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "is_dir": is_dir,
                    }
                )
            except OSError:
                continue

        anchor = Path(current.anchor) if current.anchor else current
        parent = current.parent if current != anchor else None
        return {
            "path": str(current),
            "parent": str(parent) if parent is not None else None,
            "entries": entries,
            "roots": _filesystem_roots(),
        }

    def _operation(self, action: str, payload: dict[str, Any]) -> Callable[[Logger, CancelToken], dict[str, Any]]:
        if action == "compare_keys_extract":
            role = str(payload.get("role", "main"))
            if role not in {"main", "target"}:
                raise ValueError("Chọn Database 1 hoặc Database 2.")
            with self._state_lock:
                settings = self._db_connection_cache.get(role)
            if settings is None:
                raise ValueError("Hãy kết nối database tại trang Database trước khi trích xuất key.")
            return lambda log, cancel: asdict(extract_all_compare_keys(
                settings, log, cancel=cancel.throw_if_cancelled,
            ))
        if action == "compare_keys_remove":
            return lambda log, cancel: asdict(remove_compare_keys(log))
        if action == "db_normalize":
            return lambda log, cancel: self._database_summary(
                normalize_csv_folder(
                    _text(payload, "csv_path"),
                    self._db_settings_for_role(payload.get("settings"), "main"),
                    log,
                    cancel=cancel.throw_if_cancelled,
                )
            )
        if action == "db_scan_csv":
            return lambda log, cancel: self._scan_import_csv_tables(_text(payload, "csv_path"), log)
        if action == "db_import":
            return lambda log, cancel: self._database_summary(
                import_csv_folder(
                    _text(payload, "csv_path"),
                    self._db_settings_for_role(payload.get("settings"), "main"),
                    keep_identity=_bool(payload, "keep_identity"),
                    log=log,
                    existing_row_mode=str(payload.get("existing_row_mode", "append")),
                    cancel=cancel.throw_if_cancelled,
                    table_names=payload.get("table_names"),
                )
            )
        if action == "db_export":
            return lambda log, cancel: self._database_summary(
                export_csv_folder(
                    _text(payload, "csv_path"),
                    self._db_settings_for_role(payload.get("settings"), "main"),
                    payload.get("table_names"),
                    log,
                    cancel=cancel.throw_if_cancelled,
                )
            )
        if action == "db_sync":
            return lambda log, cancel: self._database_sync(payload, log, cancel)
        if action == "db_sql_execute":
            return lambda log, cancel: self.sql_workspace.execute(
                _text(payload, "sql"),
                self._db_settings_for_role(payload.get("settings"), "main"),
                run_mode=str(payload.get("run_mode", "all")),
                write_token=str(payload.get("write_token", "")),
                log=log,
                cancel=cancel.throw_if_cancelled,
            )
        if action == "db_sql_export":
            return lambda log, cancel: self.sql_workspace.export_sources(
                _text(payload, "workspace_id"),
                self._db_settings_for_role(payload.get("settings"), "main"),
                _text(payload, "output_folder"),
                relation_ids=payload.get("relation_ids"),
                log=log,
                cancel=cancel.throw_if_cancelled,
            )
        if action == "db_sql_update":
            return lambda log, cancel: self.sql_workspace.update_source_rows(
                _text(payload, "workspace_id"),
                self._db_settings_for_role(payload.get("settings"), "main"),
                _text(payload, "relation_id"),
                payload.get("rows") if isinstance(payload.get("rows"), list) else [],
                confirmed=payload.get("confirmed") is True,
                log=log,
                cancel=cancel.throw_if_cancelled,
            )
        if action == "excel_compare":
            return lambda log, cancel: self._file_summary(
                compare_excel_workbooks(
                    _text(payload, "old_path"),
                    _text(payload, "new_path"),
                    _text(payload, "output_path"),
                    log=log,
                    cancel=cancel.throw_if_cancelled,
                )
            )
        if action == "pdf_compare":
            return lambda log, cancel: self._file_summary(
                compare_pdf_files(
                    _text(payload, "old_path"),
                    _text(payload, "new_path"),
                    _text(payload, "output_path"),
                    log=log,
                    cancel=cancel.throw_if_cancelled,
                )
            )
        operations: dict[str, Callable[[Logger], dict[str, Any]]] = {
            "compare": lambda log: self._compare(payload, log),
            "folder_compare": lambda log: self._folder_compare(payload, log),
            "format_excel_workbooks": lambda log: self._file_summary(
                format_excel_workbooks(
                    _text(payload, "root"),
                    overwrite_original=_bool(payload, "overwrite_original"),
                    recursive=_bool(payload, "recursive", True),
                    font_name=_text(payload, "font_name"),
                    font_size=payload.get("font_size", 11),
                    font_size_exclusions=payload.get("font_size_exclusions", "") if _bool(payload, "apply_exclusions", True) else "",
                    apply_font_name=_bool(payload, "apply_font_name", True),
                    apply_font_size=_bool(payload, "apply_font_size", True),
                    select_a1=_bool(payload, "select_a1", True),
                    reset_scroll=_bool(payload, "reset_scroll", True),
                    activate_first_sheet=_bool(payload, "activate_first_sheet", True),
                    log=log,
                )
            ),
            "sql_format": lambda log: self._file_summary(
                format_sql(
                    _text(payload, "sql"),
                    dialect=str(payload.get("dialect", "")),
                    log=log,
                )
            ),
            "sql_analyze": lambda log: self._file_summary(
                analyze_sql(
                    _text(payload, "sql"),
                    dialect=str(payload.get("dialect", "")),
                    log=log,
                )
            ),
            "sql_load_excel": lambda log: self._load_sql_from_excel(payload, log),
            "rename_exact": lambda log: self._file_summary(
                rename_exact_name(
                    _text(payload, "root"),
                    _text(payload, "old_name"),
                    _text(payload, "new_name"),
                    _bool(payload, "include_files", True),
                    _bool(payload, "include_folders", True),
                    log,
                )
            ),
            "rename_contains": lambda log: self._file_summary(
                rename_contains_text(
                    _text(payload, "root"),
                    _text(payload, "contains_text"),
                    str(payload.get("replacement_text", "")),
                    _bool(payload, "include_files", True),
                    _bool(payload, "include_folders", True),
                    log,
                )
            ),
            "delete_contains": lambda log: self._file_summary(
                delete_contains_text(
                    _text(payload, "root"),
                    _text(payload, "contains_text"),
                    _bool(payload, "include_files", True),
                    _bool(payload, "include_folders", True),
                    log,
                )
            ),
            "rename_sheets": lambda log: self._file_summary(
                rename_excel_sheets_contains(
                    _text(payload, "excel_path"),
                    _text(payload, "contains_text"),
                    str(payload.get("replacement_text", "")),
                    log,
                )
            ),
            "move_files": lambda log: self._file_summary(
                move_files_contains_text(
                    _text(payload, "root"),
                    _text(payload, "contains_text"),
                    _text(payload, "target_folder_name"),
                    log,
                )
            ),
            "find_empty_folders": lambda log: self._file_summary(
                find_empty_folders(_text(payload, "root"), log)
            ),
            "delete_empty_folders": lambda log: self._file_summary(
                delete_empty_folders(_text(payload, "root"), log)
            ),
            "db_test": lambda log: self._db_test(payload, log),
            "db_list_databases": lambda log: self._db_list_databases(payload, log),
            "db_list_tables": lambda log: self._db_list_tables(payload, log),
            "db_normalize": lambda log: self._database_summary(
                normalize_csv_folder(_text(payload, "csv_path"), _db_settings(payload.get("settings")), log)
            ),
            "db_scan_csv": lambda log: self._scan_import_csv_tables(_text(payload, "csv_path"), log),
            "db_import": lambda log: self._database_summary(
                import_csv_folder(
                    _text(payload, "csv_path"),
                    _db_settings(payload.get("settings")),
                    keep_identity=_bool(payload, "keep_identity"),
                    log=log,
                    existing_row_mode=str(payload.get("existing_row_mode", "append")),
                    table_names=payload.get("table_names"),
                )
            ),
            "db_export": lambda log: self._database_summary(
                export_csv_folder(
                    _text(payload, "csv_path"),
                    _db_settings(payload.get("settings")),
                    payload.get("table_names"),
                    log,
                )
            ),
            "db_sync": lambda log: self._database_sync(payload, log),
            "db_sql_execute": lambda log: self.sql_workspace.execute(
                _text(payload, "sql"),
                _db_settings(payload.get("settings")),
                run_mode=str(payload.get("run_mode", "all")),
                write_token=str(payload.get("write_token", "")),
                log=log,
            ),
            "db_sql_export": lambda log: self.sql_workspace.export_sources(
                _text(payload, "workspace_id"),
                _db_settings(payload.get("settings")),
                _text(payload, "output_folder"),
                relation_ids=payload.get("relation_ids"),
                log=log,
            ),
            "db_sql_update": lambda log: self.sql_workspace.update_source_rows(
                _text(payload, "workspace_id"),
                _db_settings(payload.get("settings")),
                _text(payload, "relation_id"),
                payload.get("rows") if isinstance(payload.get("rows"), list) else [],
                confirmed=payload.get("confirmed") is True,
                log=log,
            ),
            "apply_fixmes": lambda log: self._apply_fixmes(payload, log),
            "check_fixmes": lambda log: self._check_fixmes(log),
        }
        base_operation = operations[action]

        def operation(log: Logger, cancel: CancelToken) -> dict[str, Any]:
            cancel.throw_if_cancelled()
            result = base_operation(log)
            cancel.throw_if_cancelled()
            return result

        return operation

    def _load_sql_from_excel(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        excel_path = _text(payload, "excel_path")
        sheet_name = _text(payload, "sheet_name")
        entries = load_sql_entries_from_excel(excel_path, sheet_name)
        log(f"Đã đọc {len(entries)} SQL từ sheet “{sheet_name}”.")
        formatted = format_excel_sql_entries(
            entries,
            dialect=str(payload.get("dialect", "")),
            log=log,
        )
        result = asdict(formatted)
        result["entry_count"] = len(entries)
        result["source_sql"] = render_raw_sql_entries(entries)
        result["entries"] = [asdict(entry) for entry in entries]
        return result

    def _compare(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        selected = payload.get("workflows")
        if not isinstance(selected, list) or not selected:
            raise ValueError("Vui lòng chọn ít nhất một tùy chọn so sánh.")
        summary = process_root(
            _text(payload, "root"), log=log, selected_workflow_keys=set(map(str, selected)),
            copy_input=payload.get("copy_input") is True,
            sort_by_key=payload.get("sort_by_key") is True,
        )
        workbooks = [
            CompareWorkbookReference(
                case_folder_name=test_case.case_path.name,
                workbook_path=workbook.output_path,
                workbook_name=workbook.output_path.name,
            )
            for test_case in summary.test_cases
            for workbook in test_case.workbooks
        ]
        self._set_compare_result(summary.fixme_entries, workbooks)
        workbook_count = sum(len(case.workbooks) for case in summary.test_cases)
        return {
            "processed_count": summary.processed_count,
            "workbook_count": workbook_count,
            "error_count": len(summary.errors),
            "errors": summary.errors,
            "fixme_count": len(summary.fixme_entries),
            "fixmes": self.fixme_snapshot(),
            "compare_view": self.compare_view_index(),
        }

    def _folder_compare(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        mode = str(payload.get("export_mode", "single"))
        if mode in {"separate", "paired_single"}:
            compare_pairs = compare_csv_folder_pairs_to_workbook if mode == "paired_single" else compare_csv_folder_pairs
            summary = compare_pairs(
                _text(payload, "left"),
                _text(payload, "right"),
                _text(payload, "output"),
                payload.get("pairs") if isinstance(payload.get("pairs"), list) else [],
                log=log,
            )
            self._set_compare_result(
                summary.fixme_entries,
                [
                    CompareWorkbookReference(
                        case_folder_name=f"{summary.left_dir.name} - {summary.right_dir.name}",
                        workbook_path=output_path,
                        workbook_name=output_path.name,
                    )
                    for output_path in summary.output_paths
                ],
            )
            return {
                "output_path": str(summary.output_path),
                "sheet_count": summary.sheet_count,
                "workbook_count": summary.workbook_count,
                "fixme_count": len(summary.fixme_entries),
                "fixmes": self.fixme_snapshot(),
                "compare_view": self.compare_view_index(),
            }
        summary = compare_csv_folders(
            _text(payload, "left"),
            _text(payload, "right"),
            _text(payload, "output"),
            log=log,
        )
        self._set_compare_result(
            summary.fixme_entries,
            [
                CompareWorkbookReference(
                    case_folder_name=f"{summary.left_dir.name} - {summary.right_dir.name}",
                    workbook_path=summary.output_path,
                    workbook_name=summary.output_path.name,
                )
            ],
        )
        return {
            "output_path": str(summary.output_path),
            "sheet_count": summary.sheet_count,
            "workbook_count": summary.workbook_count,
            "fixme_count": len(summary.fixme_entries),
            "fixmes": self.fixme_snapshot(),
            "compare_view": self.compare_view_index(),
        }


    def _db_test(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        role = str(payload.get("role", "main"))
        settings = self._db_settings_for_role(payload.get("settings"), role)
        diagnostic = _log_db_connection_diagnostics(settings, log)
        try:
            test_database_connection(settings)
        except Exception as exc:
            raise RuntimeError(f"{diagnostic}; lỗi gốc: {exc}") from exc
        log("Kết nối CSDL thành công.")
        result: dict[str, Any] = {"verified": True, "role": role, "connection": _public_db_settings(settings)}
        tables: list[str] | None = None
        if payload.get("load_tables"):
            tables = list_database_tables(settings)
            result["tables"] = tables
            log(f"Đã tải {len(tables)} table.")
        self._remember_db_connection(role, settings, tables)
        return result

    def _db_list_databases(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        role = str(payload.get("role", "main"))
        settings = self._db_settings_for_role(payload.get("settings"), role)
        diagnostic = _log_db_connection_diagnostics(settings, log)
        try:
            names = list_database_names(settings)
        except Exception as exc:
            raise RuntimeError(f"{diagnostic}; lỗi gốc: {exc}") from exc
        log(f"Đã tải {len(names)} CSDL.")
        self._remember_db_connection_history(settings)
        return {"databases": names, "role": role, "connection": _public_db_settings(settings)}

    def _db_list_tables(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        role = str(payload.get("role", "main"))
        settings = self._db_settings_for_role(payload.get("settings"), role)
        tables = list_database_tables(settings)
        log(f"Đã tải {len(tables)} table.")
        with self._state_lock:
            self._remember_db_connection_history_unlocked(settings)
            self._db_table_cache[role] = list(tables)
        return {"tables": tables, "role": role, "connection": _public_db_settings(settings)}

    def _database_sync(self, payload: dict[str, Any], log: Logger, cancel: CancelToken | None = None) -> dict[str, Any]:
        summary = sync_database_tables(
            self._db_settings_for_role(payload.get("source_settings"), "main"),
            self._db_settings_for_role(payload.get("target_settings"), "target"),
            table_names=payload.get("table_names"),
            record_limit=payload.get("record_limit"),
            keep_identity=_bool(payload, "keep_identity", True),
            truncate_before_sync=_bool(payload, "truncate_before_sync"),
            log=log,
            sync_mode=str(payload.get("sync_mode", "incremental")),
            batch_size=payload.get("batch_size"),
            delete_target_only=_bool(payload, "delete_target_only", True),
            where_clause=str(payload.get("where_clause", "")),
            duplicate_mode=str(payload.get("duplicate_mode", "error")),
            cancel=cancel.throw_if_cancelled if cancel else None,
        )
        return {
            "action_name": summary.action_name,
            "table_count": summary.table_count,
            "row_count": summary.row_count,
            "source_row_count": summary.source_row_count,
            "target_row_count": summary.target_row_count,
            "inserted_count": summary.inserted_count,
            "updated_count": summary.updated_count,
            "deleted_count": summary.deleted_count,
            "unchanged_count": summary.unchanged_count,
            "retained_target_only_count": summary.retained_target_only_count,
            "backup_row_count": summary.backup_row_count,
            "backup_path": str(summary.backup_path) if summary.backup_path else "",
            "error_count": summary.error_count,
            "errors": summary.errors,
            "skipped": summary.skipped,
        }

    def _apply_fixmes(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        raw_selections = payload.get("selections")
        if not isinstance(raw_selections, dict):
            raise ValueError("Danh sách ghi chú FIXME không hợp lệ.")
        selections = {
            int(index): str(value).strip()
            for index, value in raw_selections.items()
            if str(value).strip()
        }
        if not selections:
            raise ValueError("Vui lòng chọn ít nhất một ghi chú cho các dòng FIXME.")
        with self._state_lock:
            entries = list(self._fixme_entries)
        result = apply_fixme_replacements(entries, selections)
        log(
            f"Đã áp dụng ghi chú cho {result.cell_count} ô FIXME "
            f"trong {result.workbook_count} file Excel."
        )
        return {
            "cell_count": result.cell_count,
            "workbook_count": result.workbook_count,
            "sheet_count": result.sheet_count,
            "selected_entry_count": result.selected_entry_count,
        }

    def _check_fixmes(self, log: Logger) -> dict[str, Any]:
        with self._state_lock:
            workbooks = list(self._compare_workbooks)
            fixme_entries = list(self._fixme_entries)
        known_paths = {reference.workbook_path.resolve(strict=False) for reference in workbooks}
        for entry in fixme_entries:
            workbook_path = Path(entry.workbook_path).resolve(strict=False)
            if workbook_path in known_paths:
                continue
            known_paths.add(workbook_path)
            workbooks.append(
                CompareWorkbookReference(
                    case_folder_name=entry.case_folder_name,
                    workbook_path=workbook_path,
                    workbook_name=entry.workbook_name,
                )
            )
        if not workbooks:
            raise ValueError("Chưa có file compare từ lần so sánh hiện tại để kiểm tra.")
        log(f"Đang quét toàn bộ sheet trong {len(workbooks)} file compare.")
        locations = scan_compare_workbook_fixmes(workbooks)
        if not locations:
            log("Không còn cell nào có text FIXME trong các file compare hiện tại.")
        else:
            log(f"Tìm thấy {len(locations)} cell còn text FIXME:")
            for location in locations[:200]:
                log(
                    f"- {location['case_folder_name']} | {location['workbook_name']} | "
                    f"{location['sheet_name']}!{location['cell']}"
                )
            if len(locations) > 200:
                log(f"... còn {len(locations) - 200} vị trí khác.")
        return {
            "fixme_exists": bool(locations),
            "fixme_location_count": len(locations),
            "scanned_workbook_count": len(workbooks),
            "fixme_scan_locations": locations,
            "compare_view": self.compare_view_index(),
        }

    def _set_fixmes(self, entries: list[WorkbookFixmeEntry]) -> None:
        with self._state_lock:
            self._fixme_entries = list(entries)

    def _set_compare_result(
        self,
        fixme_entries: list[WorkbookFixmeEntry],
        workbooks: list[CompareWorkbookReference],
    ) -> None:
        with self._state_lock:
            self._fixme_entries = list(fixme_entries)
            self._compare_workbooks = list(workbooks)

    @staticmethod
    def _file_summary(summary: Any) -> dict[str, Any]:
        return _jsonable(summary)

    @staticmethod
    def _database_summary(summary: Any) -> dict[str, Any]:
        return {
            "action_name": summary.action_name,
            "root_path": str(summary.root_path),
            "csv_count": summary.csv_count,
            "row_count": summary.row_count,
            "error_count": summary.error_count,
            "errors": summary.errors,
            "skipped": summary.skipped,
        }

    @staticmethod
    def _scan_import_csv_tables(root_path: str, log: Logger) -> dict[str, Any]:
        tables = scan_import_csv_tables(root_path)
        log(f"Đã quét {len(tables)} file CSV trong folder import.")
        return {
            "root_path": str(Path(root_path).expanduser().resolve()),
            "tables": [
                {
                    "table_name": item.table_name,
                    "csv_path": str(item.csv_path),
                    "file_name": item.csv_path.name,
                    "row_count": item.row_count,
                    "has_header": item.has_header,
                }
                for item in tables
            ],
        }


class AutoCompareRequestHandler(BaseHTTPRequestHandler):
    server_version = "AutoCompareWeb/1.0"

    @property
    def app(self) -> AutoCompareWebApplication:
        return self.server.application  # type: ignore[attr-defined, no-any-return]

    @property
    def app_port(self) -> int:
        return int(self.server.server_address[1])

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/bootstrap":
                self._send_json(self.app.bootstrap(self.app_port))
                return
            if parsed.path == "/api/jobs/current":
                cursor = _query_int(parse_qs(parsed.query), "cursor")
                self._send_json({"job": self.app.jobs.snapshot(cursor)})
                return
            if parsed.path == "/api/fixmes":
                self._send_json({"fixmes": self.app.fixme_snapshot()})
                return
            if parsed.path == "/api/compare-view":
                self._send_json({"compare_view": self.app.compare_view_index()})
                return
            if parsed.path == "/api/compare-view/sheet":
                query = parse_qs(parsed.query)
                self._send_json(
                    self.app.compare_sheet_snapshot(
                        query.get("workbook_id", [""])[0],
                        query.get("sheet", [""])[0],
                    )
                )
                return
            if parsed.path == "/api/fs":
                query = parse_qs(parsed.query)
                path_value = query.get("path", [""])[0]
                kind = query.get("kind", ["directory"])[0]
                extensions = query.get("ext", [])
                self._send_json(self.app.list_files(path_value, kind, extensions))
                return
            if parsed.path == "/api/sql-workspace/page":
                query = parse_qs(parsed.query)
                self._send_json(
                    self.app.sql_workspace.get_page(
                        query.get("workspace_id", [""])[0],
                        query.get("item_id", [""])[0],
                        page=_query_int(query, "page") or 1,
                        page_size=_query_int(query, "page_size") or None,
                    )
                )
                return
            self._serve_static(parsed.path)
        except Exception as exc:
            self._send_error_json(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()
            if parsed.path == "/api/image-compare":
                self._send_json(compare_images(payload.get("old"), payload.get("new")))
                return
            if parsed.path == "/api/actions":
                action = _text(payload, "action")
                job = self.app.start_action(action, payload)
                self._send_json({"job": job.snapshot()}, HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/jobs/cancel":
                self._send_json(self.app.jobs.cancel_current(str(payload.get("job_id", ""))))
                return
            if parsed.path == "/api/database/session/switch":
                self._send_json(self.app.switch_database_session_cache())
                return
            if parsed.path == "/api/sql-workspace/write-mode/enable":
                self._send_json(self.app.enable_sql_write_mode(payload))
                return
            if parsed.path == "/api/sql-workspace/inspect-execution":
                self._send_json(self.app.inspect_sql_execution(payload))
                return
            if parsed.path == "/api/sql-workspace/write-mode/disable":
                self._send_json(self.app.sql_workspace.disable_write_mode(str(payload.get("write_token", ""))))
                return
            if parsed.path == "/api/notes/save":
                self._send_json({"notes": self.app.save_note(payload)})
                return
            if parsed.path == "/api/notes/delete":
                self._send_json({"notes": self.app.delete_note(payload)})
                return
            if parsed.path == "/api/folder-compare/pairs":
                self._send_json(self.app.preview_folder_compare_pairs(payload))
                return
            if parsed.path == "/api/excel-format-presets/save":
                self._send_json({"presets": self.app.save_excel_format_preset(payload)})
                return
            if parsed.path == "/api/excel-format-presets/delete":
                self._send_json({"presets": self.app.delete_excel_format_preset(payload)})
                return
            raise FileNotFoundError(f"API không tồn tại: {parsed.path}")
        except Exception as exc:
            self._send_error_json(exc)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("API chỉ chấp nhận nội dung application/json.")
        length = int(self.headers.get("Content-Length", "0"))
        limit = 34_000_000 if urlparse(self.path).path == "/api/image-compare" else 10_000_000
        if length <= 0 or length > limit:
            raise ValueError("Nội dung request trống hoặc quá lớn.")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Nội dung JSON phải là một object.")
        return data

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        static_root = STATIC_DIR.resolve()
        target = (static_root / relative).resolve()
        if static_root not in target.parents and target != static_root:
            raise PermissionError("Đường dẫn static không hợp lệ.")
        if not target.exists() or not target.is_file():
            target = static_root / "index.html"
        content_type, _ = mimetypes.guess_type(target.name)
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _send_error_json(self, exc: Exception) -> None:
        if isinstance(exc, FileNotFoundError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, PermissionError):
            status = HTTPStatus.FORBIDDEN
        elif isinstance(exc, RuntimeError):
            status = HTTPStatus.CONFLICT
        else:
            status = HTTPStatus.BAD_REQUEST
        self._send_json({"error": str(exc)}, status)


class AutoCompareServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, SO_REUSEADDR allows a second process to bind the same port.
    # Requests can then reach an older backend even after run.bat starts again.
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], application: AutoCompareWebApplication) -> None:
        self.application = application
        super().__init__(address, AutoCompareRequestHandler)


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("Port phải nằm trong khoảng 1 đến 65535.")
    if not STATIC_DIR.exists():
        raise FileNotFoundError(f"Không tìm thấy giao diện web: {STATIC_DIR}")

    application = AutoCompareWebApplication()
    server = AutoCompareServer((host, port), application)
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{browser_host}:{server.server_address[1]}"
    print(f"AutoCompare is running at {url}")
    print("Press Ctrl+C to stop the server.")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStopping AutoCompare...")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Khởi động giao diện web AutoCompare")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Địa chỉ bind (mặc định: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port HTTP (mặc định: {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    args = parser.parse_args(argv)
    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


def _db_settings(raw_value: Any) -> DatabaseConnectionSettings:
    if not isinstance(raw_value, dict):
        raise ValueError("Thông tin kết nối CSDL không hợp lệ.")
    return DatabaseConnectionSettings(
        database_type=str(raw_value.get("database_type", "SQL Server")),
        host=str(raw_value.get("host", "")),
        database=str(raw_value.get("database", "")),
        schema=str(raw_value.get("schema", "")),
        port=str(raw_value.get("port", "")),
        username=str(raw_value.get("username", "")),
        password=str(raw_value.get("password", "")),
        trusted_connection=raw_value.get("trusted_connection") is True,
        driver=str(raw_value.get("driver") or preferred_sqlserver_driver(get_available_sqlserver_drivers())),
        trust_server_certificate=raw_value.get("trust_server_certificate", True) is True,
        encrypt=raw_value.get("encrypt", False) is True,
    )


def _public_db_settings(settings: DatabaseConnectionSettings) -> dict[str, Any]:
    return {
        "database_type": database_label(settings.database_type),
        "host": settings.host,
        "database": settings.database,
        "schema": settings.schema,
        "port": settings.port,
        "username": settings.username,
        "password": "",
        "trusted_connection": settings.trusted_connection,
        "driver": settings.driver,
        "trust_server_certificate": settings.trust_server_certificate,
        "encrypt": settings.encrypt,
    }


def _log_db_connection_diagnostics(settings: DatabaseConnectionSettings, log: Logger) -> str:
    if settings.normalized_type != "sqlserver":
        message = f"Cấu hình kết nối CSDL: type={database_label(settings.database_type)}; host={settings.host or '(chưa nhập host)'}"
        log(message)
        return message
    server = settings.host.strip() or "(chưa nhập server)"
    if settings.port.strip():
        server = f"{server},{settings.port.strip()}"
    auth = "Windows Auth" if settings.trusted_connection else f"SQL Auth user={settings.username or '(chưa nhập user)'}"
    if is_modern_sqlserver_odbc_driver(settings.driver):
        encrypt = "yes" if settings.encrypt else "no"
        trust = "yes" if settings.trust_server_certificate else "no"
        encryption = f"Encrypt={encrypt}; TrustServerCertificate={trust}"
    else:
        encryption = "Encrypt keyword: omitted for legacy driver"
    message = (
        "Cấu hình kết nối SQL Server: "
        f"server={server}; database={settings.database or '(chưa nhập database)'}; "
        f"driver={settings.driver}; auth={auth}; {encryption}"
    )
    log(message)
    return message


def _db_connection_history_path() -> Path:
    return Path.cwd() / DB_CONNECTION_HISTORY_FILE


def _load_db_connection_history() -> dict[str, DatabaseConnectionSettings]:
    path = _db_connection_history_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = raw.get("connections") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return {}

    history: dict[str, DatabaseConnectionSettings] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            settings = _db_settings(item)
        except ValueError:
            continue
        if not settings.host.strip() and not settings.database.strip():
            continue
        key = _db_connection_history_key(settings)
        if key in history:
            del history[key]
        history[key] = settings
        while len(history) > DB_CONNECTION_HISTORY_LIMIT:
            oldest_key = next(iter(history))
            del history[oldest_key]
    return history


def _save_db_connection_history(history: list[DatabaseConnectionSettings]) -> None:
    path = _db_connection_history_path()
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "connections": [asdict(settings) for settings in history[-DB_CONNECTION_HISTORY_LIMIT:]],
    }
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _db_settings_match_except_password(left: DatabaseConnectionSettings, right: DatabaseConnectionSettings) -> bool:
    return (
        database_label(left.database_type).casefold() == database_label(right.database_type).casefold()
        and left.host.strip().casefold() == right.host.strip().casefold()
        and left.database.strip().casefold() == right.database.strip().casefold()
        and left.schema.strip().casefold() == right.schema.strip().casefold()
        and left.port.strip() == right.port.strip()
        and left.username.strip().casefold() == right.username.strip().casefold()
        and left.trusted_connection == right.trusted_connection
        and left.driver.strip().casefold() == right.driver.strip().casefold()
        and left.trust_server_certificate == right.trust_server_certificate
        and left.encrypt == right.encrypt
    )


def _db_settings_match_server_login_except_password(
    left: DatabaseConnectionSettings,
    right: DatabaseConnectionSettings,
) -> bool:
    return (
        database_label(left.database_type).casefold() == database_label(right.database_type).casefold()
        and left.host.strip().casefold() == right.host.strip().casefold()
        and left.port.strip() == right.port.strip()
        and left.username.strip().casefold() == right.username.strip().casefold()
        and left.trusted_connection == right.trusted_connection
        and left.driver.strip().casefold() == right.driver.strip().casefold()
        and left.trust_server_certificate == right.trust_server_certificate
        and left.encrypt == right.encrypt
    )


def _db_connection_history_key(settings: DatabaseConnectionSettings) -> str:
    parts = (
        database_label(settings.database_type),
        settings.host,
        settings.database,
        settings.schema,
        settings.port,
        settings.username,
        str(settings.trusted_connection),
        settings.driver,
        str(settings.trust_server_certificate),
        str(settings.encrypt),
    )
    return "\x1f".join(str(part).strip().casefold() for part in parts)


def _fixme_to_dict(entry: WorkbookFixmeEntry, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "case_folder_name": entry.case_folder_name,
        "workbook_path": str(entry.workbook_path),
        "workbook_name": entry.workbook_name,
        "csv_file_name": entry.csv_file_name,
        "source_sheet_name": Path(entry.csv_file_name).with_suffix("").as_posix(),
        "sheet_name": entry.sheet_name,
        "column_name": entry.column_name,
        "left_value": entry.left_value,
        "right_value": entry.right_value,
        "record_number": entry.record_number,
        "fixme_cell": entry.fixme_cell,
    }


def _note_to_dict(note: FixmeNote) -> dict[str, str]:
    return {"value": note.value, "meaning": note.meaning}


def _excel_format_preset_to_dict(preset: ExcelFormatPreset) -> dict[str, Any]:
    return {
        "name": preset.name,
        "font_name": preset.font_name,
        "font_size": preset.font_size,
        "exclusions": list(preset.exclusions),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value


def _filesystem_roots() -> list[str]:
    if Path.cwd().drive:
        roots = [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
        return roots or [str(Path.cwd().anchor)]
    return ["/"]


def _text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"Thiếu giá trị bắt buộc: {key}.")
    return value


def _bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    return value is True


def _query_int(query: dict[str, list[str]], key: str) -> int:
    try:
        return int(query.get(key, ["0"])[0])
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
