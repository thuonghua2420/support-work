from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .app_config import AppConfig, load_app_config
from .copy_ut import run_copy_ut_files
from .database_io import (
    DatabaseConnectionSettings,
    database_type_options,
    default_port,
    default_schema,
    export_csv_folder,
    get_available_sqlserver_drivers,
    import_csv_folder,
    list_database_names,
    list_database_tables,
    normalize_csv_folder,
    sync_database_tables,
    test_database_connection,
)
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
from .folder_compare import compare_csv_folders
from .processor import process_root

APP_TITLE = "AutoCompare"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "web"
Logger = Callable[[str], None]


@dataclass
class WebJob:
    id: str
    action: str
    label: str
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
        }


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: WebJob | None = None

    def start(
        self,
        action: str,
        label: str,
        operation: Callable[[Logger], dict[str, Any]],
    ) -> WebJob:
        with self._lock:
            if self._current is not None and self._current.state in {"queued", "running"}:
                raise RuntimeError("Một tác vụ khác đang chạy. Vui lòng chờ tác vụ hiện tại hoàn tất.")
            job = WebJob(id=uuid.uuid4().hex, action=action, label=label, status=label)
            self._current = job

        worker = threading.Thread(target=self._run, args=(job, operation), daemon=True)
        worker.start()
        return job

    def snapshot(self, cursor: int = 0) -> dict[str, Any] | None:
        with self._lock:
            if self._current is None:
                return None
            return self._current.snapshot(cursor)

    def _run(self, job: WebJob, operation: Callable[[Logger], dict[str, Any]]) -> None:
        with self._lock:
            job.state = "running"
            job.started_at = _now_iso()

        def log(message: str) -> None:
            with self._lock:
                job.logs.append(str(message))

        try:
            result = operation(log)
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
        "compare": "Đang chạy so sánh UT...",
        "folder_compare": "Đang so sánh hai folder CSV...",
        "copy_ut": "Đang sao chép file UT...",
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
        "db_import": "Đang nhập CSV vào CSDL...",
        "db_export": "Đang xuất CSDL ra CSV...",
        "db_sync": "Đang đồng bộ hai CSDL...",
        "apply_fixmes": "Đang áp dụng ghi chú FIXME...",
    }
    CONFIRMED_ACTIONS = {
        "delete_contains",
        "delete_empty_folders",
        "db_import",
        "db_export",
        "db_sync",
    }

    def __init__(self) -> None:
        self.config: AppConfig = load_app_config()
        self.note_store = FixmeNoteStore()
        self.jobs = JobManager()
        self._state_lock = threading.Lock()
        self._fixme_entries: list[WorkbookFixmeEntry] = []

    def bootstrap(self, port: int) -> dict[str, Any]:
        notes = self.note_store.load()
        return {
            "app_title": APP_TITLE,
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
            "database_types": database_type_options(),
            "database_defaults": {
                database_type: {
                    "port": default_port(database_type),
                    "schema": default_schema(database_type),
                }
                for database_type in database_type_options()
            },
            "sqlserver_drivers": get_available_sqlserver_drivers(),
            "notes": [_note_to_dict(note) for note in notes],
            "fixmes": self.fixme_snapshot(),
            "job": self.jobs.snapshot(),
        }

    def fixme_snapshot(self) -> list[dict[str, Any]]:
        with self._state_lock:
            return [_fixme_to_dict(entry, index) for index, entry in enumerate(self._fixme_entries)]

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

    def start_action(self, action: str, payload: dict[str, Any]) -> WebJob:
        if action not in self.ACTION_LABELS:
            raise ValueError(f"Tác vụ không được hỗ trợ: {action}")
        if action in self.CONFIRMED_ACTIONS and payload.get("confirmed") is not True:
            raise PermissionError("Tác vụ này cần được xác nhận rõ ràng trước khi chạy.")
        operation = self._operation(action, payload)
        return self.jobs.start(action, self.ACTION_LABELS[action], operation)

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

    def _operation(self, action: str, payload: dict[str, Any]) -> Callable[[Logger], dict[str, Any]]:
        operations: dict[str, Callable[[Logger], dict[str, Any]]] = {
            "compare": lambda log: self._compare(payload, log),
            "folder_compare": lambda log: self._folder_compare(payload, log),
            "copy_ut": lambda log: self._copy_ut(payload, log),
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
            "db_import": lambda log: self._database_summary(
                import_csv_folder(
                    _text(payload, "csv_path"),
                    _db_settings(payload.get("settings")),
                    keep_identity=_bool(payload, "keep_identity"),
                    log=log,
                    existing_row_mode=str(payload.get("existing_row_mode", "append")),
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
            "apply_fixmes": lambda log: self._apply_fixmes(payload, log),
        }
        return operations[action]

    def _compare(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        selected = payload.get("workflows")
        if not isinstance(selected, list) or not selected:
            raise ValueError("Vui lòng chọn ít nhất một tùy chọn so sánh.")
        summary = process_root(_text(payload, "root"), log=log, selected_workflow_keys=set(map(str, selected)))
        self._set_fixmes(summary.fixme_entries)
        workbook_count = sum(len(case.workbooks) for case in summary.test_cases)
        return {
            "processed_count": summary.processed_count,
            "workbook_count": workbook_count,
            "error_count": len(summary.errors),
            "errors": summary.errors,
            "fixme_count": len(summary.fixme_entries),
            "fixmes": self.fixme_snapshot(),
        }

    def _folder_compare(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        summary = compare_csv_folders(
            _text(payload, "left"),
            _text(payload, "right"),
            _text(payload, "output"),
            log=log,
        )
        self._set_fixmes(summary.fixme_entries)
        return {
            "output_path": str(summary.output_path),
            "sheet_count": summary.sheet_count,
            "fixme_count": len(summary.fixme_entries),
            "fixmes": self.fixme_snapshot(),
        }

    def _copy_ut(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        log_path = run_copy_ut_files(_text(payload, "source"), _text(payload, "target"), log)
        return {"log_path": str(log_path)}

    def _db_test(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        settings = _db_settings(payload.get("settings"))
        test_database_connection(settings)
        log("Kết nối CSDL thành công.")
        result: dict[str, Any] = {"verified": True, "role": str(payload.get("role", "main"))}
        if payload.get("load_tables"):
            tables = list_database_tables(settings)
            result["tables"] = tables
            log(f"Đã tải {len(tables)} table.")
        return result

    def _db_list_databases(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        names = list_database_names(_db_settings(payload.get("settings")))
        log(f"Đã tải {len(names)} CSDL.")
        return {"databases": names, "role": str(payload.get("role", "main"))}

    def _db_list_tables(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        tables = list_database_tables(_db_settings(payload.get("settings")))
        log(f"Đã tải {len(tables)} table.")
        return {"tables": tables, "role": str(payload.get("role", "main"))}

    def _database_sync(self, payload: dict[str, Any], log: Logger) -> dict[str, Any]:
        summary = sync_database_tables(
            _db_settings(payload.get("source_settings")),
            _db_settings(payload.get("target_settings")),
            table_names=payload.get("table_names"),
            record_limit=payload.get("record_limit"),
            keep_identity=_bool(payload, "keep_identity", True),
            truncate_before_sync=_bool(payload, "truncate_before_sync"),
            log=log,
            sync_mode=str(payload.get("sync_mode", "incremental")),
            batch_size=payload.get("batch_size"),
            delete_target_only=_bool(payload, "delete_target_only", True),
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
        return {"cell_count": result.cell_count, "workbook_count": result.workbook_count}

    def _set_fixmes(self, entries: list[WorkbookFixmeEntry]) -> None:
        with self._state_lock:
            self._fixme_entries = list(entries)

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
            if parsed.path == "/api/fs":
                query = parse_qs(parsed.query)
                path_value = query.get("path", [""])[0]
                kind = query.get("kind", ["directory"])[0]
                extensions = query.get("ext", [])
                self._send_json(self.app.list_files(path_value, kind, extensions))
                return
            self._serve_static(parsed.path)
        except Exception as exc:
            self._send_error_json(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()
            if parsed.path == "/api/actions":
                action = _text(payload, "action")
                job = self.app.start_action(action, payload)
                self._send_json({"job": job.snapshot()}, HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/notes/save":
                self._send_json({"notes": self.app.save_note(payload)})
                return
            if parsed.path == "/api/notes/delete":
                self._send_json({"notes": self.app.delete_note(payload)})
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
        if length <= 0 or length > 1_000_000:
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
    allow_reuse_address = True

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
        driver=str(raw_value.get("driver", "ODBC Driver 18 for SQL Server")),
        trust_server_certificate=raw_value.get("trust_server_certificate", True) is True,
        encrypt=raw_value.get("encrypt", True) is True,
    )


def _fixme_to_dict(entry: WorkbookFixmeEntry, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "case_folder_name": entry.case_folder_name,
        "workbook_path": str(entry.workbook_path),
        "workbook_name": entry.workbook_name,
        "csv_file_name": entry.csv_file_name,
        "sheet_name": entry.sheet_name,
        "column_name": entry.column_name,
        "left_value": entry.left_value,
        "right_value": entry.right_value,
        "record_number": entry.record_number,
        "fixme_cell": entry.fixme_cell,
    }


def _note_to_dict(note: FixmeNote) -> dict[str, str]:
    return {"value": note.value, "meaning": note.meaning}


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
