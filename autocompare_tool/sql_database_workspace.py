from __future__ import annotations

import atexit
import base64
import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, time as datetime_time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from sqlglot import exp

from .app_config import DatabaseWorkspaceConfig
from .database_io import (
    DatabaseAdapter,
    DatabaseColumn,
    DatabaseConnectionSettings,
    TableMetadata,
    TableNotFoundError,
    apply_query_timeout,
    database_sqlglot_dialect,
    format_database_value,
    get_adapter,
    validate_connection_settings,
)
from .dbeaver_csv import write_typed_dbeaver_csv_rows
from .sql_tools import analyze_sql, parse_sql_expressions, render_sql_expression


Logger = Callable[[str], None]
WHERE_COLOR = "#22c55e"
SELECT_COLOR = "#facc15"
JOIN_COLORS = (
    "#2563eb",
    "#7c3aed",
    "#db2777",
    "#f97316",
    "#0891b2",
    "#4f46e5",
    "#be123c",
    "#0f766e",
    "#9333ea",
    "#ea580c",
)
READ_STATEMENT_KEYS = {
    "select",
    "union",
    "intersect",
    "except",
}
WRITE_TOKEN_PREFIX = "wsql_"
WORKSPACE_TTL_SECONDS = 60 * 60


@dataclass
class _SpoolItem:
    item_id: str
    kind: str
    label: str
    columns: list[dict[str, Any]]
    row_count: int = 0
    statement_index: int = 0
    relation_id: str = ""
    page_size: int = 100
    unsupported_reason: str = ""


@dataclass
class _Workspace:
    workspace_id: str
    root_path: Path
    sqlite_path: Path
    fingerprint: str
    dialect: str
    created_at: float
    expires_at: float
    settings: DatabaseConnectionSettings
    analysis: dict[str, Any] | None = None
    statements: list[dict[str, Any]] = field(default_factory=list)
    results: list[_SpoolItem] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    relations: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class _WriteToken:
    token: str
    fingerprint: str
    expires_at: float


class SqlDatabaseWorkspaceManager:
    """Business logic for the Database / SQL Workspace page.

    The manager keeps only short-lived workspaces in memory. Database connections are
    opened per operation and closed immediately after that operation.
    """

    def __init__(self, config: DatabaseWorkspaceConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._workspaces: dict[str, _Workspace] = {}
        self._write_tokens: dict[str, _WriteToken] = {}
        self._root_path = Path(tempfile.mkdtemp(prefix="autocompare_sql_workspace_"))
        atexit.register(self.close)

    def close(self) -> None:
        with self._lock:
            self._workspaces.clear()
            self._write_tokens.clear()
            root_path = self._root_path
        shutil.rmtree(root_path, ignore_errors=True)

    def enable_write_mode(self, settings: DatabaseConnectionSettings) -> dict[str, Any]:
        self._cleanup_expired()
        validated = validate_connection_settings(settings)
        adapter = get_adapter(validated.normalized_type)
        connection = adapter.connect(validated)
        try:
            cursor = connection.cursor()
            adapter.execute(cursor, adapter.test_sql())
            _safe_rollback(connection)
        finally:
            connection.close()
        token = WRITE_TOKEN_PREFIX + uuid.uuid4().hex
        expires_at = time.time() + self.config.write_mode_timeout_minutes * 60
        with self._lock:
            self._write_tokens[token] = _WriteToken(
                token=token,
                fingerprint=connection_fingerprint(validated),
                expires_at=expires_at,
            )
        return {
            "write_token": token,
            "expires_at": _iso_from_timestamp(expires_at),
            "timeout_minutes": self.config.write_mode_timeout_minutes,
        }

    def disable_write_mode(self, token: str) -> dict[str, Any]:
        with self._lock:
            if token:
                self._write_tokens.pop(str(token), None)
        return {"disabled": True}

    def execute(
        self,
        sql_text: str,
        settings: DatabaseConnectionSettings,
        *,
        run_mode: str = "all",
        write_token: str = "",
        log: Logger | None = None,
    ) -> dict[str, Any]:
        logger = log or (lambda _message: None)
        self._cleanup_expired()
        validated = validate_connection_settings(settings)
        dialect = database_sqlglot_dialect(validated.database_type)
        fingerprint = connection_fingerprint(validated)
        normalized_sql = str(sql_text or "").strip()
        if not normalized_sql:
            raise ValueError("Vui lòng nhập câu SQL cần xử lý.")

        expressions: list[exp.Expression] = []
        parse_error = ""
        try:
            expressions = parse_sql_expressions(normalized_sql, dialect)
        except Exception as exc:
            parse_error = str(exc)

        run_mode = str(run_mode or "all").strip().lower()
        if run_mode not in {"all", "current"}:
            raise ValueError(f"Chế độ chạy SQL không hợp lệ: {run_mode}")
        if parse_error and run_mode == "all":
            raise ValueError("Run all yêu cầu parser tách statement thành công: " + parse_error)

        raw_mode = bool(parse_error)
        if raw_mode and not self._is_write_token_valid(write_token, fingerprint):
            raise PermissionError(
                "SQL không parse được; chỉ cho chạy raw SQL khi Write mode đang bật và token còn hợp lệ."
            )

        statement_sqls: list[str]
        statement_exprs: list[exp.Expression | None]
        if raw_mode:
            statement_sqls = [normalized_sql]
            statement_exprs = [None]
        else:
            statement_sqls = [render_sql_expression(expression, dialect) for expression in expressions]
            statement_exprs = list(expressions)

        write_required = raw_mode or any(not is_read_statement(expression) for expression in statement_exprs if expression)
        if write_required and not self._is_write_token_valid(write_token, fingerprint):
            raise PermissionError("DDL/DML chỉ được chạy khi Write mode hợp lệ.")

        workspace = self._create_workspace(validated, fingerprint, dialect)
        adapter = get_adapter(validated.normalized_type)
        connection = adapter.connect(validated)
        logger(
            f"SQL Workspace: chạy {len(statement_sqls)} statement trên {validated.database_type}; "
            f"{'Write mode' if write_required else 'read-only'}."
        )

        committed = False
        rolled_back = False
        failed = False
        try:
            for index, statement_sql in enumerate(statement_sqls, start=1):
                expression = statement_exprs[index - 1]
                statement_result = self._execute_one_statement(
                    workspace,
                    adapter,
                    connection,
                    statement_sql,
                    expression,
                    index,
                )
                workspace.statements.append(statement_result)
                if statement_result.get("error"):
                    failed = True
                    break

            if not raw_mode and not failed:
                self._analyze_and_spool_sources(workspace, adapter, connection, normalized_sql, expressions, dialect)

            if failed:
                _safe_rollback(connection)
                rolled_back = True
            elif write_required:
                connection.commit()
                committed = True
            else:
                _safe_rollback(connection)
        finally:
            connection.close()

        if committed:
            transaction_status = "committed"
        elif rolled_back:
            transaction_status = "rolled_back"
        else:
            transaction_status = "read_only"
        for statement in workspace.statements:
            statement["transaction_status"] = transaction_status

        response = self._workspace_response(workspace)
        response["parse_error"] = parse_error
        response["transaction_status"] = transaction_status
        return response

    def get_page(
        self,
        workspace_id: str,
        item_id: str,
        *,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        workspace = self._get_workspace(workspace_id)
        size = self._validated_page_size(page_size)
        safe_page = max(1, int(page or 1))
        offset = (safe_page - 1) * size
        item = self._find_item(workspace, item_id)
        with workspace.lock:
            rows = _read_spool_rows(workspace.sqlite_path, item_id, offset, size)
        return {
            "workspace_id": workspace.workspace_id,
            "item_id": item.item_id,
            "kind": item.kind,
            "label": item.label,
            "page": safe_page,
            "page_size": size,
            "row_count": item.row_count,
            "columns": item.columns,
            "rows": [
                _spooled_row_to_response(row, item.columns)
                for row in rows
            ],
        }

    def export_sources(
        self,
        workspace_id: str,
        settings: DatabaseConnectionSettings,
        output_folder: str | Path,
        *,
        relation_ids: Iterable[str] | None = None,
        log: Logger | None = None,
    ) -> dict[str, Any]:
        logger = log or (lambda _message: None)
        validated = validate_connection_settings(settings)
        workspace = self._get_workspace(workspace_id)
        if connection_fingerprint(validated) != workspace.fingerprint:
            raise PermissionError("Kết nối hiện tại đã khác workspace SQL. Hãy chạy lại SQL trước khi export.")

        selected = {str(item) for item in relation_ids or [] if str(item).strip()}
        output_path = Path(output_folder).expanduser()
        output_path.mkdir(parents=True, exist_ok=True)
        adapter = get_adapter(validated.normalized_type)
        connection = adapter.connect(validated)
        exported: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        errors: list[str] = []
        try:
            for source in workspace.sources:
                relation_id = str(source.get("relation_id", ""))
                if selected and relation_id not in selected:
                    continue
                relation = workspace.relations.get(relation_id)
                if not relation:
                    skipped.append({"relation_id": relation_id, "reason": "Không tìm thấy source trong workspace."})
                    continue
                if source.get("lineage_status") != "exact":
                    skipped.append(
                        {
                            "relation_id": relation_id,
                            "reason": str(source.get("unsupported_reason") or "Không thể truy vết chính xác."),
                        }
                    )
                    continue
                try:
                    exported.append(
                        self._export_one_source(workspace, source, relation, connection, adapter, output_path, logger)
                    )
                except Exception as exc:
                    errors.append(f"{source.get('label', relation_id)}: {exc}")
        finally:
            connection.close()

        return {
            "workspace_id": workspace.workspace_id,
            "output_folder": str(output_path),
            "files": exported,
            "skipped": skipped,
            "error_count": len(errors),
            "errors": errors,
        }

    def update_source_rows(
        self,
        workspace_id: str,
        settings: DatabaseConnectionSettings,
        relation_id: str,
        rows: Sequence[dict[str, Any]],
        *,
        confirmed: bool = False,
        log: Logger | None = None,
    ) -> dict[str, Any]:
        if not confirmed:
            raise PermissionError("Update Data cần xác nhận riêng trước khi ghi vào database.")
        logger = log or (lambda _message: None)
        validated = validate_connection_settings(settings)
        workspace = self._get_workspace(workspace_id)
        if connection_fingerprint(validated) != workspace.fingerprint:
            raise PermissionError("Kết nối hiện tại đã khác workspace SQL. Hãy chạy lại SQL trước khi update.")

        relation = workspace.relations.get(str(relation_id))
        if not relation:
            raise ValueError("Không tìm thấy source cần update trong workspace.")
        if not relation.get("updateable"):
            raise PermissionError(str(relation.get("read_only_reason") or "Source này không cho update."))
        if not rows:
            raise ValueError("Không có dòng dirty để update.")

        adapter = get_adapter(validated.normalized_type)
        metadata = _metadata_from_relation(relation)
        primary_keys = [column for column in metadata.columns if column.is_primary_key]
        editable_by_name = {
            column.name.lower(): column
            for column in metadata.columns
            if _is_editable_column(column)
        }
        connection = adapter.connect(validated)
        updated_rows: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        try:
            for row_payload in rows:
                row_number = int(row_payload.get("row_number", 0))
                row_token = str(row_payload.get("row_token", ""))
                values = row_payload.get("values")
                if row_number <= 0 or not row_token or not isinstance(values, dict):
                    raise ValueError("Payload update không hợp lệ.")
                original = _read_one_spool_row(workspace.sqlite_path, _source_item_id(relation_id), row_number)
                if original is None or original["row_hash"] != row_token:
                    conflicts.append({"row_number": row_number, "reason": "Snapshot row trong workspace đã thay đổi."})
                    continue

                original_values = _deserialize_row_payload(str(original["payload"]))
                pk_values = [
                    original_values[_column_index(metadata, key.name)]
                    for key in primary_keys
                ]
                current_row = _select_row_by_pk(connection, adapter, metadata, primary_keys, pk_values)
                if current_row is None:
                    conflicts.append({"row_number": row_number, "reason": "Row đã bị xóa hoặc primary key không còn tồn tại."})
                    continue
                current_hash = _row_hash(current_row, metadata.columns)
                if current_hash != row_token:
                    conflicts.append({"row_number": row_number, "reason": "Row đã bị người khác sửa sau khi grid được tải."})
                    continue

                update_columns: list[DatabaseColumn] = []
                update_values: list[object] = []
                for raw_name, raw_value in values.items():
                    column = editable_by_name.get(str(raw_name).lower())
                    if column is None:
                        raise PermissionError(f"Column {raw_name} không được phép update.")
                    update_columns.append(column)
                    update_values.append(_coerce_editor_value(raw_value, column))
                if not update_columns:
                    continue
                _update_row_by_pk(connection, adapter, metadata, update_columns, update_values, primary_keys, pk_values)
                reloaded = _select_row_by_pk(connection, adapter, metadata, primary_keys, pk_values)
                if reloaded is None:
                    raise RuntimeError("Không thể reload row vừa update.")
                updated_rows.append(
                    {
                        "row_number": row_number,
                        "values": reloaded,
                        "row_hash": _row_hash(reloaded, metadata.columns),
                    }
                )

            if conflicts:
                connection.rollback()
                return {
                    "updated_count": 0,
                    "conflicts": conflicts,
                    "rolled_back": True,
                    "stale": True,
                }
            connection.commit()
            with workspace.lock:
                for updated in updated_rows:
                    _replace_spool_row(
                        workspace.sqlite_path,
                        _source_item_id(relation_id),
                        int(updated["row_number"]),
                        updated["values"],
                        metadata.columns,
                    )
            logger(f"Đã update {len(updated_rows)} row trong {metadata.schema}.{metadata.name}.")
        except Exception:
            _safe_rollback(connection)
            raise
        finally:
            connection.close()

        return {
            "updated_count": len(updated_rows),
            "conflicts": [],
            "rolled_back": False,
            "stale": True,
        }

    def _create_workspace(
        self,
        settings: DatabaseConnectionSettings,
        fingerprint: str,
        dialect: str,
    ) -> _Workspace:
        workspace_id = uuid.uuid4().hex
        root_path = self._root_path / workspace_id
        root_path.mkdir(parents=True, exist_ok=True)
        sqlite_path = root_path / "spool.sqlite3"
        _init_spool(sqlite_path)
        workspace = _Workspace(
            workspace_id=workspace_id,
            root_path=root_path,
            sqlite_path=sqlite_path,
            fingerprint=fingerprint,
            dialect=dialect,
            created_at=time.time(),
            expires_at=time.time() + WORKSPACE_TTL_SECONDS,
            settings=settings,
        )
        with self._lock:
            self._workspaces[workspace_id] = workspace
        return workspace

    def _execute_one_statement(
        self,
        workspace: _Workspace,
        adapter: DatabaseAdapter,
        connection,
        statement_sql: str,
        expression: exp.Expression | None,
        statement_index: int,
    ) -> dict[str, Any]:
        cursor = connection.cursor()
        apply_query_timeout(cursor, self.config.query_timeout_seconds)
        statement_type = statement_type_name(expression, statement_sql)
        started = time.perf_counter()
        try:
            adapter.execute(cursor, statement_sql)
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            result: dict[str, Any] = {
                "statement_index": statement_index,
                "statement_type": statement_type,
                "sql": statement_sql,
                "elapsed_ms": elapsed_ms,
                "affected_rows": getattr(cursor, "rowcount", -1),
                "has_result_set": bool(cursor.description),
            }
            if cursor.description:
                columns = _columns_from_description(cursor.description)
                item_id = f"result-{statement_index}"
                row_count = _spool_cursor(
                    workspace,
                    item_id,
                    "result",
                    cursor,
                    columns,
                    self.config.export_batch_size,
                    self.config.workspace_spool_limit_mb,
                )
                item = _SpoolItem(
                    item_id=item_id,
                    kind="result",
                    label=f"Statement {statement_index}",
                    columns=[_column_to_dict(column, editable=False) for column in columns],
                    row_count=row_count,
                    statement_index=statement_index,
                    page_size=self.config.page_size,
                )
                workspace.results.append(item)
                result["result_item_id"] = item_id
                result["row_count"] = row_count
            return result
        except Exception as exc:
            return {
                "statement_index": statement_index,
                "statement_type": statement_type,
                "sql": statement_sql,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "affected_rows": getattr(cursor, "rowcount", -1),
                "has_result_set": False,
                "error": str(exc),
            }

    def _analyze_and_spool_sources(
        self,
        workspace: _Workspace,
        adapter: DatabaseAdapter,
        connection,
        sql_text: str,
        expressions: list[exp.Expression],
        dialect: str,
    ) -> None:
        analysis = analyze_sql(sql_text, dialect)
        workspace.analysis = _jsonable(analysis)
        relations = _build_relations(workspace, adapter, connection, expressions, analysis, dialect)
        _decorate_column_usage(expressions, relations)
        for relation in relations:
            workspace.relations[relation["relation_id"]] = relation
            source = _source_summary_from_relation(relation)
            workspace.sources.append(source)
            if relation.get("lineage_status") != "exact":
                continue
            try:
                cursor = connection.cursor()
                apply_query_timeout(cursor, self.config.query_timeout_seconds)
                adapter.execute(cursor, str(relation["source_sql"]))
                metadata = _metadata_from_relation(relation)
                if not metadata.columns and cursor.description:
                    metadata = TableMetadata(
                        schema=metadata.schema,
                        name=metadata.name,
                        columns=_columns_from_description(cursor.description),
                        relation_type=metadata.relation_type,
                    )
                    relation["metadata"] = _metadata_to_dict(metadata)
                    relation["columns"] = [_column_to_dict(column, editable=False) for column in metadata.columns]
                    source["columns"] = relation["columns"]
                    source["updateable"] = False
                if not metadata.columns:
                    raise RuntimeError("Không đọc được metadata column từ source data.")
                row_count = _spool_cursor(
                    workspace,
                    _source_item_id(relation["relation_id"]),
                    "source",
                    cursor,
                    metadata.columns,
                    self.config.export_batch_size,
                    self.config.workspace_spool_limit_mb,
                )
                relation["row_count"] = row_count
                source["row_count"] = row_count
                source["item_id"] = _source_item_id(relation["relation_id"])
            except Exception as exc:
                reason = f"Không thể đọc source data chính xác: {exc}"
                relation["lineage_status"] = "unsupported"
                relation["unsupported_reason"] = reason
                source["lineage_status"] = "unsupported"
                source["unsupported_reason"] = reason

    def _workspace_response(self, workspace: _Workspace) -> dict[str, Any]:
        results = [self._item_response(workspace, item) for item in workspace.results]
        source_responses: list[dict[str, Any]] = []
        for source in workspace.sources:
            source_copy = dict(source)
            item_id = str(source_copy.get("item_id", ""))
            if item_id:
                item = self._find_item(workspace, item_id)
                source_copy["first_page"] = self.get_page(workspace.workspace_id, item.item_id, page=1)
            source_responses.append(source_copy)
        return {
            "workspace_id": workspace.workspace_id,
            "dialect": workspace.dialect,
            "statements": workspace.statements,
            "results": results,
            "sources": source_responses,
            "analysis": workspace.analysis,
            "warnings": workspace.warnings,
        }

    def _item_response(self, workspace: _Workspace, item: _SpoolItem) -> dict[str, Any]:
        return {
            "item_id": item.item_id,
            "kind": item.kind,
            "label": item.label,
            "statement_index": item.statement_index,
            "relation_id": item.relation_id,
            "row_count": item.row_count,
            "columns": item.columns,
            "first_page": self.get_page(workspace.workspace_id, item.item_id, page=1),
        }

    def _find_item(self, workspace: _Workspace, item_id: str) -> _SpoolItem:
        for item in workspace.results:
            if item.item_id == item_id:
                return item
        for source in workspace.sources:
            if source.get("item_id") == item_id:
                relation_id = str(source.get("relation_id", ""))
                relation = workspace.relations.get(relation_id, {})
                return _SpoolItem(
                    item_id=item_id,
                    kind="source",
                    label=str(source.get("label") or relation_id),
                    columns=list(relation.get("columns", [])),
                    row_count=int(source.get("row_count", 0)),
                    statement_index=int(source.get("statement_index", 0)),
                    relation_id=relation_id,
                    page_size=self.config.page_size,
                )
        raise KeyError(f"Không tìm thấy dữ liệu trang: {item_id}")

    def _get_workspace(self, workspace_id: str) -> _Workspace:
        self._cleanup_expired()
        with self._lock:
            workspace = self._workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError("SQL workspace đã hết hạn hoặc không tồn tại. Hãy chạy lại SQL.")
        return workspace

    def _validated_page_size(self, value: int | None) -> int:
        if value is None:
            return self.config.page_size
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = self.config.page_size
        return min(max(1, parsed), self.config.max_page_size)

    def _cleanup_expired(self) -> None:
        now = time.time()
        with self._lock:
            expired_workspaces = [
                workspace_id
                for workspace_id, workspace in self._workspaces.items()
                if workspace.expires_at <= now
            ]
            for workspace_id in expired_workspaces:
                workspace = self._workspaces.pop(workspace_id)
                shutil.rmtree(workspace.root_path, ignore_errors=True)
            expired_tokens = [
                token
                for token, token_info in self._write_tokens.items()
                if token_info.expires_at <= now
            ]
            for token in expired_tokens:
                self._write_tokens.pop(token, None)

    def _is_write_token_valid(self, token: str, fingerprint: str) -> bool:
        if not token:
            return False
        self._cleanup_expired()
        with self._lock:
            token_info = self._write_tokens.get(str(token))
        return bool(token_info and token_info.fingerprint == fingerprint and token_info.expires_at > time.time())

    def _export_one_source(
        self,
        workspace: _Workspace,
        source: dict[str, Any],
        relation: dict[str, Any],
        connection,
        adapter: DatabaseAdapter,
        output_path: Path,
        logger: Logger,
    ) -> dict[str, Any]:
        metadata = _metadata_from_relation(relation)
        item_id = str(source["item_id"])
        file_path = _unique_export_path(output_path, source, relation)
        negative_row, negative_reason = _find_negative_row(
            workspace,
            item_id,
            relation,
            connection,
            adapter,
            self.config.export_batch_size,
        )

        def row_iter() -> Iterable[Sequence[str | None]]:
            for row in _iter_spooled_value_rows(workspace.sqlite_path, item_id):
                yield [
                    format_database_value(row[index], column)
                    for index, column in enumerate(metadata.columns)
                ]
            if negative_row is not None:
                yield [
                    format_database_value(negative_row[index], column)
                    for index, column in enumerate(metadata.columns)
                ]

        written = write_typed_dbeaver_csv_rows(
            file_path,
            [column.name for column in metadata.columns],
            row_iter(),
            [column.should_quote_export for column in metadata.columns],
        )
        matched_count = int(source.get("row_count", 0))
        logger(f"Export {source.get('label', item_id)} -> {file_path} ({written} dòng).")
        return {
            "relation_id": relation["relation_id"],
            "path": str(file_path),
            "matched_record_count": matched_count,
            "negative_record_count": 1 if negative_row is not None else 0,
            "negative_reason": "" if negative_row is not None else negative_reason,
        }


def is_read_statement(expression: exp.Expression) -> bool:
    key = getattr(expression, "key", "").lower()
    class_name = expression.__class__.__name__.lower()
    if key in READ_STATEMENT_KEYS or class_name in READ_STATEMENT_KEYS:
        return not _select_writes_to_table(expression)
    return False


def statement_type_name(expression: exp.Expression | None, sql_text: str = "") -> str:
    if expression is not None:
        key = getattr(expression, "key", "")
        if key:
            return key.upper()
        return expression.__class__.__name__.upper()
    stripped = str(sql_text or "").lstrip()
    return stripped.split(None, 1)[0].upper() if stripped else "RAW"


def connection_fingerprint(settings: DatabaseConnectionSettings) -> str:
    validated = validate_connection_settings(settings)
    payload = {
        "database_type": validated.normalized_type,
        "host": validated.host,
        "database": validated.database,
        "schema": validated.schema,
        "port": validated.port,
        "username": validated.username,
        "password_hash": hashlib.sha256(validated.password.encode("utf-8")).hexdigest(),
        "trusted_connection": validated.trusted_connection,
        "driver": validated.driver,
        "trust_server_certificate": validated.trust_server_certificate,
        "encrypt": validated.encrypt,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _select_writes_to_table(expression: exp.Expression) -> bool:
    for node in expression.walk():
        if node.__class__.__name__.lower() == "into":
            return True
    return False


def _init_spool(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS spool_rows (
                item_id TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                payload TEXT NOT NULL,
                row_hash TEXT NOT NULL,
                pk_payload TEXT,
                PRIMARY KEY (item_id, row_number)
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_spool_rows_item ON spool_rows(item_id, row_number)")


def _spool_cursor(
    workspace: _Workspace,
    item_id: str,
    _kind: str,
    cursor,
    columns: list[DatabaseColumn],
    batch_size: int,
    spool_limit_mb: int,
) -> int:
    row_number = 0
    max_bytes = max(1, int(spool_limit_mb)) * 1024 * 1024
    with workspace.lock, sqlite3.connect(workspace.sqlite_path) as spool:
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            payloads = []
            for row in rows:
                values = list(row)
                row_number += 1
                row_hash = _row_hash(values, columns)
                pk_payload = _serialize_pk_payload(values, columns)
                payloads.append((item_id, row_number, _serialize_row_payload(values), row_hash, pk_payload))
            spool.executemany(
                "INSERT INTO spool_rows(item_id, row_number, payload, row_hash, pk_payload) VALUES (?, ?, ?, ?, ?)",
                payloads,
            )
            spool.commit()
            if workspace.sqlite_path.stat().st_size > max_bytes:
                raise RuntimeError("SQL workspace vượt quá giới hạn spool tạm thời trong cấu hình.")
    return row_number


def _read_spool_rows(sqlite_path: Path, item_id: str, offset: int, limit: int) -> list[sqlite3.Row]:
    with sqlite3.connect(sqlite_path) as connection:
        connection.row_factory = sqlite3.Row
        return list(
            connection.execute(
                """
                SELECT item_id, row_number, payload, row_hash, pk_payload
                FROM spool_rows
                WHERE item_id = ?
                ORDER BY row_number
                LIMIT ? OFFSET ?
                """,
                (item_id, limit, offset),
            )
        )


def _read_one_spool_row(sqlite_path: Path, item_id: str, row_number: int) -> sqlite3.Row | None:
    with sqlite3.connect(sqlite_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            """
            SELECT item_id, row_number, payload, row_hash, pk_payload
            FROM spool_rows
            WHERE item_id = ? AND row_number = ?
            """,
            (item_id, row_number),
        ).fetchone()


def _replace_spool_row(
    sqlite_path: Path,
    item_id: str,
    row_number: int,
    values: Sequence[object],
    columns: list[DatabaseColumn],
) -> None:
    row_hash = _row_hash(values, columns)
    pk_payload = _serialize_pk_payload(values, columns)
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            """
            UPDATE spool_rows
            SET payload = ?, row_hash = ?, pk_payload = ?
            WHERE item_id = ? AND row_number = ?
            """,
            (_serialize_row_payload(values), row_hash, pk_payload, item_id, row_number),
        )


def _spooled_row_to_response(row: sqlite3.Row, columns: list[dict[str, Any]]) -> dict[str, Any]:
    values = _deserialize_row_payload(str(row["payload"]))
    return {
        "row_number": int(row["row_number"]),
        "row_token": str(row["row_hash"]),
        "values": [
            _display_value(values[index], columns[index])
            for index in range(min(len(values), len(columns)))
        ],
        "raw_values": [_serialize_value(value) for value in values],
    }


def _iter_spooled_value_rows(sqlite_path: Path, item_id: str) -> Iterable[list[object]]:
    offset = 0
    batch_size = 5000
    while True:
        rows = _read_spool_rows(sqlite_path, item_id, offset, batch_size)
        if not rows:
            break
        for row in rows:
            yield _deserialize_row_payload(str(row["payload"]))
        offset += len(rows)


def _serialize_row_payload(values: Sequence[object]) -> str:
    return json.dumps([_serialize_value(value) for value in values], ensure_ascii=False, separators=(",", ":"))


def _deserialize_row_payload(payload: str) -> list[object]:
    return [_deserialize_value(value) for value in json.loads(payload)]


def _serialize_value(value: object) -> dict[str, Any]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": value}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": format(value, "f")}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, datetime_time):
        return {"type": "time", "value": value.isoformat()}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "bytes", "value": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "str", "value": str(value)}


def _deserialize_value(payload: dict[str, Any]) -> object:
    value_type = payload.get("type")
    value = payload.get("value")
    if value_type == "null":
        return None
    if value_type in {"bool", "int", "float", "str"}:
        return value
    if value_type == "decimal":
        return Decimal(str(value))
    if value_type == "datetime":
        return datetime.fromisoformat(str(value))
    if value_type == "date":
        return date.fromisoformat(str(value))
    if value_type == "time":
        return datetime_time.fromisoformat(str(value))
    if value_type == "bytes":
        return base64.b64decode(str(value).encode("ascii"))
    return value


def _row_hash(values: Sequence[object], columns: list[DatabaseColumn]) -> str:
    payload = [
        {"name": column.name, "value": _serialize_value(values[index] if index < len(values) else None)}
        for index, column in enumerate(columns)
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _serialize_pk_payload(values: Sequence[object], columns: list[DatabaseColumn]) -> str:
    keys = [
        {"name": column.name, "value": _serialize_value(values[index] if index < len(values) else None)}
        for index, column in enumerate(columns)
        if column.is_primary_key
    ]
    return json.dumps(keys, ensure_ascii=False, separators=(",", ":"))


def _display_value(value: object, column: dict[str, Any]) -> str:
    if value is None:
        return "[NULL]"
    db_column = DatabaseColumn(
        name=str(column.get("name", "")),
        ordinal=int(column.get("index", 0) or 0),
        data_type=str(column.get("data_type", "unknown")),
        nullable=bool(column.get("nullable", True)),
        numeric_scale=_optional_int(column.get("numeric_scale")),
        numeric_precision=_optional_int(column.get("numeric_precision")),
        is_primary_key=bool(column.get("is_primary_key", False)),
    )
    formatted = format_database_value(value, db_column)
    return "" if formatted is None else formatted


def _columns_from_description(description: Sequence[Sequence[object]]) -> list[DatabaseColumn]:
    columns: list[DatabaseColumn] = []
    for index, item in enumerate(description, start=1):
        type_value = item[1] if len(item) > 1 else None
        columns.append(
            DatabaseColumn(
                name=str(item[0]),
                ordinal=index,
                data_type=getattr(type_value, "__name__", None) or str(type_value or "unknown"),
                nullable=True,
            )
        )
    return columns


def _column_to_dict(column: DatabaseColumn, *, editable: bool) -> dict[str, Any]:
    return {
        "index": column.ordinal,
        "name": column.name,
        "data_type": column.data_type,
        "nullable": column.nullable,
        "numeric_scale": column.numeric_scale,
        "numeric_precision": column.numeric_precision,
        "is_primary_key": column.is_primary_key,
        "is_identity": column.is_identity,
        "is_generated": column.is_generated,
        "is_rowversion": column.is_rowversion,
        "editable": editable,
        "locked_reason": "" if editable else _locked_reason(column),
        "usages": [],
        "usage": "",
        "color": "",
        "join_group": "",
        "join_tooltip": "",
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


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")


def _safe_rollback(connection) -> None:
    try:
        connection.rollback()
    except Exception:
        return


def _optional_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_relations(
    workspace: _Workspace,
    adapter: DatabaseAdapter,
    connection,
    expressions: list[exp.Expression],
    analysis,
    dialect: str,
) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    expression_by_index = {index: expression for index, expression in enumerate(expressions, start=1)}
    for occurrence_index, table_ref in enumerate(analysis.tables, start=1):
        relation_id = f"s{table_ref.statement_index}.q{_safe_token(table_ref.scope_id)}.r{occurrence_index}"
        metadata: TableMetadata | None = None
        relation_kind = _relation_kind(table_ref.source_type)
        unresolved_reason = ""
        if table_ref.source_type == "TABLE":
            try:
                metadata = adapter.get_relation(
                    connection,
                    workspace.settings,
                    table_ref.name,
                    table_ref.schema or None,
                )
                relation_kind = metadata.relation_type
            except TableNotFoundError as exc:
                unresolved_reason = str(exc)
            except Exception as exc:
                unresolved_reason = f"Không đọc được metadata: {exc}"

        if metadata is None:
            metadata = TableMetadata(
                schema=table_ref.schema or "",
                name=table_ref.name or table_ref.qualified_name,
                columns=[],
                relation_type=relation_kind,
            )

        statement = expression_by_index.get(table_ref.statement_index)
        source_sql = ""
        trace_sql = ""
        lineage_strategy = ""
        lineage_status = "unsupported"
        unsupported_reason = unresolved_reason or "Source logic không phải base table/view có metadata."
        if (
            statement is not None
            and table_ref.role not in {"INSERT TARGET", "UPDATE TARGET", "DELETE TARGET", "CREATE TARGET", "MERGE TARGET"}
            and not unresolved_reason
        ):
            source_sql, unsupported_reason, trace_sql, lineage_strategy = _diagnostic_source_sql(
                statement,
                table_ref,
                metadata,
                adapter,
                dialect,
            )
            if source_sql:
                lineage_status = "exact"

        editable_columns = [_is_editable_column(column) for column in metadata.columns]
        read_only_reason = _read_only_reason(metadata, lineage_status, unsupported_reason)
        updateable = not read_only_reason
        columns = [
            _column_to_dict(column, editable=updateable and editable_columns[index])
            for index, column in enumerate(metadata.columns)
        ]
        for index, column in enumerate(columns):
            if updateable and not editable_columns[index]:
                column["locked_reason"] = _locked_reason(metadata.columns[index])

        relation = {
            "relation_id": relation_id,
            "statement_index": table_ref.statement_index,
            "scope_id": table_ref.scope_id,
            "scope_name": table_ref.scope_name,
            "depth": table_ref.depth,
            "relation_kind": relation_kind,
            "source_type": table_ref.source_type,
            "role": table_ref.role,
            "schema": metadata.schema,
            "name": metadata.name,
            "qualified_name": _qualified_name(metadata),
            "alias": table_ref.alias,
            "display_name": table_ref.alias or metadata.name or table_ref.qualified_name,
            "columns": columns,
            "lineage_status": lineage_status,
            "unsupported_reason": "" if lineage_status == "exact" else unsupported_reason,
            "lineage_reason": lineage_strategy if lineage_status == "exact" else unsupported_reason,
            "source_sql": source_sql,
            "trace_sql": trace_sql,
            "lineage_strategy": lineage_strategy,
            "row_count": 0,
            "updateable": updateable,
            "read_only_reason": read_only_reason,
            "metadata": _metadata_to_dict(metadata),
        }
        relations.append(relation)
    return relations


def _legacy_projection_source_sql(statement: exp.Expression, table_ref, dialect: str) -> tuple[str, str]:
    if not is_read_statement(statement) or getattr(statement, "key", "").lower() != "select":
        return "", "Chỉ hỗ trợ truy vết exact cho SELECT đơn giản."
    if table_ref.depth != 0:
        return "", "Source nằm trong CTE/subquery nên không rewrite exact ở scope ngoài."
    unsupported = _unsupported_select_lineage_reason(statement)
    if unsupported:
        return "", unsupported
    alias = table_ref.alias or table_ref.name
    try:
        clone = statement.copy()
        clone.set("expressions", [exp.Column(this=exp.Star(), table=exp.Identifier(this=alias))])
        clone.set("distinct", exp.Distinct())
        clone.set("order", None)
        return render_sql_expression(clone, dialect), ""
    except Exception as exc:
        return "", f"Không thể sinh diagnostic query exact: {exc}"


def _unsupported_select_lineage_reason(statement: exp.Expression) -> str:
    if statement.args.get("with"):
        return "CTE cần lineage projection riêng nên chưa trả source data exact."
    if statement.args.get("group"):
        return "GROUP BY/aggregate làm thay đổi cardinality nguồn."
    if statement.args.get("having"):
        return "HAVING cần lineage sau aggregate."
    if statement.args.get("qualify"):
        return "QUALIFY cần lineage sau window."
    if statement.args.get("limit") or statement.args.get("offset"):
        return "LIMIT/OFFSET làm tập record tham gia phụ thuộc thứ tự."
    if statement.args.get("distinct"):
        return "SELECT DISTINCT làm tập record tham gia không luôn ánh xạ 1-1."
    unsupported_classes = {
        "aggfunc",
        "window",
        "subquery",
        "exists",
        "union",
        "intersect",
        "except",
        "pivot",
    }
    for node in statement.walk():
        class_name = node.__class__.__name__.lower()
        if class_name in unsupported_classes or class_name.endswith("agg"):
            return f"{node.__class__.__name__} chưa được hỗ trợ strict lineage."
    return ""


def _diagnostic_source_sql(
    statement: exp.Expression,
    table_ref,
    metadata: TableMetadata,
    adapter: DatabaseAdapter,
    dialect: str,
) -> tuple[str, str, str, str]:
    if not is_read_statement(statement) or getattr(statement, "key", "").lower() != "select":
        return "", "Chỉ hỗ trợ truy vết exact cho SELECT.", "", ""
    if table_ref.depth != 0:
        return "", "Source nằm trong CTE/subquery cần đẩy predicate qua projection lineage.", "", ""
    unsupported = _unsupported_select_trace_reason(statement)
    if unsupported:
        return "", unsupported, "", ""
    alias = table_ref.alias or table_ref.name
    if not alias:
        return "", "Source không có alias/tên để rewrite trace.", "", ""
    try:
        primary_keys = [column for column in metadata.columns if column.is_primary_key]
        if (
            table_ref.source_type == "TABLE"
            and metadata.relation_type == "table"
            and primary_keys
            and not statement.args.get("with")
        ):
            trace_sql, key_aliases = _matched_primary_key_trace_sql(statement, alias, primary_keys, dialect)
            source_sql = _source_sql_from_primary_key_trace(adapter, metadata, trace_sql, primary_keys, key_aliases)
            return source_sql, "", trace_sql, "exact matched primary-key trace"
        if table_ref.source_type == "TABLE" and not metadata.columns:
            return "", "Source chưa có metadata/projection để trả grid chính xác.", "", ""
        source_sql = _alias_projection_source_sql(statement, alias, dialect)
        return source_sql, "", "", "exact source projection"
    except Exception as exc:
        return "", f"Không thể sinh diagnostic query exact: {exc}", "", ""


def _unsupported_select_trace_reason(statement: exp.Expression) -> str:
    if statement.args.get("group"):
        return "GROUP BY/aggregate cần trace theo group key và HAVING nên chưa trả source data exact."
    if statement.args.get("having"):
        return "HAVING cần lineage sau aggregate."
    if statement.args.get("qualify"):
        return "QUALIFY cần lineage sau window."
    if statement.args.get("limit") or statement.args.get("offset"):
        return "LIMIT/OFFSET làm tập record tham gia phụ thuộc thứ tự."
    unsupported_classes = {
        "union",
        "intersect",
        "except",
        "pivot",
    }
    for node in statement.walk():
        class_name = node.__class__.__name__.lower()
        if class_name in unsupported_classes:
            return f"{node.__class__.__name__} chưa được hỗ trợ strict lineage."
    return ""


def _matched_primary_key_trace_sql(
    statement: exp.Expression,
    alias: str,
    primary_keys: list[DatabaseColumn],
    dialect: str,
) -> tuple[str, list[str]]:
    clone = statement.copy()
    key_aliases = [_trace_key_alias(index) for index, _column in enumerate(primary_keys, start=1)]
    clone.set(
        "expressions",
        [
            exp.Alias(
                this=_column_expression(alias, column.name),
                alias=exp.Identifier(this=key_aliases[index], quoted=True),
            )
            for index, column in enumerate(primary_keys)
        ],
    )
    clone.set("distinct", exp.Distinct())
    clone.set("order", None)
    return render_sql_expression(clone, dialect), key_aliases


def _alias_projection_source_sql(statement: exp.Expression, alias: str, dialect: str) -> str:
    clone = statement.copy()
    clone.set("expressions", [exp.Column(this=exp.Star(), table=exp.Identifier(this=alias))])
    clone.set("distinct", exp.Distinct())
    clone.set("order", None)
    return render_sql_expression(clone, dialect)


def _source_sql_from_primary_key_trace(
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    trace_sql: str,
    primary_keys: list[DatabaseColumn],
    key_aliases: list[str],
) -> str:
    source_alias = adapter.quote_identifier("__ac_source")
    keys_alias = adapter.quote_identifier("__ac_keys")
    column_sql = ", ".join(
        f"{source_alias}.{adapter.quote_identifier(column.name)}"
        for column in metadata.columns
    )
    join_sql = " AND ".join(
        f"{source_alias}.{adapter.quote_identifier(column.name)} = {keys_alias}.{adapter.quote_identifier(key_aliases[index])}"
        for index, column in enumerate(primary_keys)
    )
    order_sql = ", ".join(
        f"{source_alias}.{adapter.quote_identifier(column.name)}"
        for column in primary_keys
    )
    return (
        f"SELECT {column_sql} "
        f"FROM {adapter.qualified_table(metadata)} {source_alias} "
        f"INNER JOIN ({trace_sql}) {keys_alias} ON {join_sql} "
        f"ORDER BY {order_sql}"
    )


def _column_expression(table_alias: str, column_name: str) -> exp.Column:
    return exp.Column(
        this=exp.Identifier(this=column_name, quoted=True),
        table=exp.Identifier(this=table_alias, quoted=False),
    )


def _trace_key_alias(index: int) -> str:
    return f"__ac_pk_{index}"


def _relation_kind(source_type: str) -> str:
    if source_type == "CTE_REFERENCE":
        return "CTE"
    if source_type == "QUERY_REFERENCE":
        return "derived"
    return "table"


def _source_summary_from_relation(relation: dict[str, Any]) -> dict[str, Any]:
    return {
        "relation_id": relation["relation_id"],
        "item_id": _source_item_id(relation["relation_id"]) if relation.get("lineage_status") == "exact" else "",
        "statement_index": relation["statement_index"],
        "label": _relation_label(relation),
        "relation_kind": relation["relation_kind"],
        "qualified_name": relation["qualified_name"],
        "alias": relation["alias"],
        "scope_id": relation["scope_id"],
        "lineage_status": relation["lineage_status"],
        "unsupported_reason": relation["unsupported_reason"],
        "row_count": relation.get("row_count", 0),
        "columns": relation.get("columns", []),
        "updateable": relation.get("updateable", False),
        "read_only_reason": relation.get("read_only_reason", ""),
    }


def _source_item_id(relation_id: str) -> str:
    return f"source-{relation_id}"


def _relation_label(relation: dict[str, Any]) -> str:
    alias = str(relation.get("alias") or "").strip()
    base = str(relation.get("qualified_name") or relation.get("name") or relation.get("relation_id"))
    return f"{base} AS {alias}" if alias else base


def _decorate_column_usage(expressions: list[exp.Expression], relations: list[dict[str, Any]]) -> None:
    relation_lookup = {relation["relation_id"]: relation for relation in relations}
    usage: dict[tuple[str, str], set[str]] = {}
    join_edges: list[tuple[tuple[str, str], tuple[str, str], str]] = []

    for statement_index, statement in enumerate(expressions, start=1):
        statement_relations = [relation for relation in relations if relation["statement_index"] == statement_index]
        if not statement_relations:
            continue
        for select in statement.find_all(exp.Select):
            projection_expressions = list(select.args.get("expressions") or [])
            for projection in projection_expressions:
                for resolved in _resolve_projection_columns(projection, statement_relations):
                    usage.setdefault(resolved, set()).add("SELECT")
            where = select.args.get("where")
            if where is not None:
                for column in where.find_all(exp.Column):
                    resolved = _resolve_column(column, statement_relations)
                    if resolved:
                        usage.setdefault(resolved, set()).add("WHERE")
                _collect_join_edges_from_condition(where.this, statement_relations, join_edges)
            for join in select.args.get("joins") or []:
                on = join.args.get("on")
                if on is None:
                    continue
                for column in on.find_all(exp.Column):
                    resolved = _resolve_column(column, statement_relations)
                    if resolved:
                        usage.setdefault(resolved, set()).add("JOIN")
                _collect_join_edges_from_condition(on, statement_relations, join_edges)

    union = _UnionFind()
    edge_expression_by_key: dict[tuple[str, str], set[str]] = {}
    for left, right, expression_sql in join_edges:
        union.add(left)
        union.add(right)
        union.union(left, right)
        edge_expression_by_key.setdefault(left, set()).add(expression_sql)
        edge_expression_by_key.setdefault(right, set()).add(expression_sql)

    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for key in union.items:
        groups.setdefault(union.find(key), []).append(key)
    group_by_key: dict[tuple[str, str], str] = {}
    tooltip_by_key: dict[tuple[str, str], str] = {}
    for group_index, members in enumerate(groups.values(), start=1):
        group_id = f"J{group_index}"
        for member in members:
            group_by_key[member] = group_id
            tooltip_by_key[member] = _join_tooltip(member, members, edge_expression_by_key, relation_lookup)

    color_by_group = {
        group_id: JOIN_COLORS[index % len(JOIN_COLORS)]
        for index, group_id in enumerate(sorted(set(group_by_key.values())))
    }

    for relation in relations:
        for column in relation.get("columns", []):
            key = (relation["relation_id"], str(column.get("name", "")).lower())
            column_usages = usage.get(key, set())
            if key in group_by_key:
                column_usages.add("JOIN")
                column["join_group"] = group_by_key[key]
                column["join_tooltip"] = tooltip_by_key.get(key, "")
            column["usages"] = sorted(column_usages)
            if "JOIN" in column_usages:
                column["usage"] = "JOIN"
                column["color"] = color_by_group.get(str(column.get("join_group")), JOIN_COLORS[0])
            elif "WHERE" in column_usages:
                column["usage"] = "WHERE"
                column["color"] = WHERE_COLOR
            elif "SELECT" in column_usages:
                column["usage"] = "SELECT"
                column["color"] = SELECT_COLOR


def _resolve_projection_columns(
    projection: exp.Expression,
    relations: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    resolved: list[tuple[str, str]] = []
    if isinstance(projection, exp.Star):
        for relation in relations:
            resolved.extend((relation["relation_id"], str(column.get("name", "")).lower()) for column in relation.get("columns", []))
        return resolved
    if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
        table = projection.table
        for relation in _relations_for_table(table, relations):
            resolved.extend((relation["relation_id"], str(column.get("name", "")).lower()) for column in relation.get("columns", []))
        return resolved
    for star in projection.find_all(exp.Star):
        parent = star.parent
        if isinstance(parent, exp.Column):
            table = parent.table
            for relation in _relations_for_table(table, relations):
                resolved.extend((relation["relation_id"], str(column.get("name", "")).lower()) for column in relation.get("columns", []))
    for column in projection.find_all(exp.Column):
        if isinstance(column.this, exp.Star):
            continue
        item = _resolve_column(column, relations)
        if item:
            resolved.append(item)
    return _unique_pairs(resolved)


def _collect_join_edges_from_condition(
    condition: exp.Expression,
    relations: list[dict[str, Any]],
    join_edges: list[tuple[tuple[str, str], tuple[str, str], str]],
) -> None:
    for node in condition.find_all(exp.EQ):
        columns = [column for column in node.find_all(exp.Column) if not isinstance(column.this, exp.Star)]
        if len(columns) < 2:
            continue
        resolved = [_resolve_column(column, relations) for column in columns]
        resolved = [item for item in resolved if item is not None]
        if len(resolved) < 2:
            continue
        first = resolved[0]
        for item in resolved[1:]:
            if item[0] != first[0] or item[1] != first[1]:
                join_edges.append((first, item, node.sql()))


def _resolve_column(column: exp.Column, relations: list[dict[str, Any]]) -> tuple[str, str] | None:
    column_name = column.name
    if not column_name:
        return None
    if column.table:
        candidates = _relations_for_table(column.table, relations)
        for relation in candidates:
            if _relation_has_column(relation, column_name):
                return relation["relation_id"], column_name.lower()
        return None
    candidates = [relation for relation in relations if _relation_has_column(relation, column_name)]
    if len(candidates) == 1:
        return candidates[0]["relation_id"], column_name.lower()
    return None


def _relations_for_table(table: str, relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    value = str(table or "").lower()
    return [
        relation
        for relation in relations
        if value
        and value in {
            str(relation.get("alias") or "").lower(),
            str(relation.get("name") or "").lower(),
            str(relation.get("qualified_name") or "").lower(),
        }
    ]


def _relation_has_column(relation: dict[str, Any], column_name: str) -> bool:
    target = column_name.lower()
    return any(str(column.get("name", "")).lower() == target for column in relation.get("columns", []))


def _join_tooltip(
    member: tuple[str, str],
    members: list[tuple[str, str]],
    expressions_by_key: dict[tuple[str, str], set[str]],
    relation_lookup: dict[str, dict[str, Any]],
) -> str:
    details: list[str] = [f"Column hiện tại: {_join_member_detail(member, relation_lookup)}"]
    joined_members = [item for item in members if item != member]
    if joined_members:
        details.append("Join với:")
        details.extend(f"- {_join_member_detail(item, relation_lookup)}" for item in joined_members)
    expression_set: set[str] = set()
    for item in members:
        expression_set.update(expressions_by_key.get(item, set()))
    expressions = sorted(expression_set)
    if expressions:
        details.append("Biểu thức JOIN:")
        details.extend(f"- {expression}" for expression in expressions)
    return "\n".join(details)


def _join_member_detail(member: tuple[str, str], relation_lookup: dict[str, dict[str, Any]]) -> str:
    relation_id, column_name = member
    relation = relation_lookup.get(relation_id, {})
    column = _column_dict_by_name(relation, column_name)
    alias = str(relation.get("alias") or "").strip()
    qualified_name = str(relation.get("qualified_name") or relation.get("name") or relation_id)
    display_column = str(column.get("name") or column_name)
    index = column.get("index", "?")
    alias_text = f" AS {alias}" if alias else ""
    return f"{qualified_name}{alias_text}.{display_column} (index #{index})"


def _column_dict_by_name(relation: dict[str, Any], column_name: str) -> dict[str, Any]:
    target = column_name.lower()
    for column in relation.get("columns", []):
        if str(column.get("name", "")).lower() == target:
            return column
    return {}


def _unique_pairs(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in values:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    @property
    def items(self) -> set[tuple[str, str]]:
        return set(self.parent)

    def add(self, item: tuple[str, str]) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: tuple[str, str]) -> tuple[str, str]:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _metadata_to_dict(metadata: TableMetadata) -> dict[str, Any]:
    return {
        "schema": metadata.schema,
        "name": metadata.name,
        "relation_type": metadata.relation_type,
        "columns": [_database_column_to_plain(column) for column in metadata.columns],
    }


def _metadata_from_relation(relation: dict[str, Any]) -> TableMetadata:
    metadata = relation.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Source không có metadata hợp lệ.")
    return TableMetadata(
        schema=str(metadata.get("schema", "")),
        name=str(metadata.get("name", "")),
        relation_type=str(metadata.get("relation_type", relation.get("relation_kind", "table"))),
        columns=[_database_column_from_plain(item) for item in metadata.get("columns", [])],
    )


def _database_column_to_plain(column: DatabaseColumn) -> dict[str, Any]:
    return {
        "name": column.name,
        "ordinal": column.ordinal,
        "data_type": column.data_type,
        "nullable": column.nullable,
        "default_value": column.default_value,
        "is_identity": column.is_identity,
        "identity_generation": column.identity_generation,
        "is_computed": column.is_computed,
        "generated_expression": column.generated_expression,
        "numeric_scale": column.numeric_scale,
        "numeric_precision": column.numeric_precision,
        "is_primary_key": column.is_primary_key,
    }


def _database_column_from_plain(value: dict[str, Any]) -> DatabaseColumn:
    return DatabaseColumn(
        name=str(value.get("name", "")),
        ordinal=int(value.get("ordinal", value.get("index", 0)) or 0),
        data_type=str(value.get("data_type", "unknown")),
        nullable=bool(value.get("nullable", True)),
        default_value=value.get("default_value"),
        is_identity=bool(value.get("is_identity", False)),
        identity_generation=str(value.get("identity_generation", "")),
        is_computed=bool(value.get("is_computed", False)),
        generated_expression=value.get("generated_expression"),
        numeric_scale=_optional_int(value.get("numeric_scale")),
        numeric_precision=_optional_int(value.get("numeric_precision")),
        is_primary_key=bool(value.get("is_primary_key", False)),
    )


def _read_only_reason(metadata: TableMetadata, lineage_status: str, unsupported_reason: str) -> str:
    if metadata.relation_type != "table":
        return "Chỉ base table mới được update."
    if lineage_status != "exact":
        return unsupported_reason or "Source chưa có lineage exact."
    if not any(column.is_primary_key for column in metadata.columns):
        return "Table không có primary key nên không update an toàn."
    return ""


def _is_editable_column(column: DatabaseColumn) -> bool:
    return not _locked_reason(column)


def _locked_reason(column: DatabaseColumn) -> str:
    if column.is_primary_key:
        return "primary key"
    if column.is_identity:
        return "identity"
    if column.is_generated:
        return "generated/computed"
    if column.is_rowversion:
        return "rowversion"
    type_name = column.normalized_type_name
    blocked_markers = ("binary", "blob", "image", "bytea", "raw", "clob", "nclob", "lob")
    if any(marker in type_name for marker in blocked_markers):
        return "binary/LOB"
    return ""


def _qualified_name(metadata: TableMetadata) -> str:
    return f"{metadata.schema}.{metadata.name}" if metadata.schema else metadata.name


def _column_index(metadata: TableMetadata, column_name: str) -> int:
    target = column_name.lower()
    for index, column in enumerate(metadata.columns):
        if column.name.lower() == target:
            return index
    raise KeyError(f"Column không tồn tại trong metadata: {column_name}")


def _select_row_by_pk(
    connection,
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    primary_keys: list[DatabaseColumn],
    pk_values: Sequence[object],
) -> list[object] | None:
    cursor = connection.cursor()
    column_sql = ", ".join(adapter.quote_identifier(column.name) for column in metadata.columns)
    where_sql = " AND ".join(
        f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(index)}"
        for index, column in enumerate(primary_keys)
    )
    adapter.execute(cursor, f"SELECT {column_sql} FROM {adapter.qualified_table(metadata)} WHERE {where_sql}", pk_values)
    row = cursor.fetchone()
    return list(row) if row is not None else None


def _update_row_by_pk(
    connection,
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    update_columns: list[DatabaseColumn],
    update_values: Sequence[object],
    primary_keys: list[DatabaseColumn],
    pk_values: Sequence[object],
) -> None:
    cursor = connection.cursor()
    set_sql = ", ".join(
        f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(index)}"
        for index, column in enumerate(update_columns)
    )
    where_offset = len(update_columns)
    where_sql = " AND ".join(
        f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(where_offset + index)}"
        for index, column in enumerate(primary_keys)
    )
    adapter.execute(
        cursor,
        f"UPDATE {adapter.qualified_table(metadata)} SET {set_sql} WHERE {where_sql}",
        [*update_values, *pk_values],
    )
    rowcount = getattr(cursor, "rowcount", -1)
    if rowcount == 0:
        raise RuntimeError("Không có row nào được update; có thể primary key đã thay đổi.")


def _coerce_editor_value(raw_value: object, column: DatabaseColumn) -> object:
    if isinstance(raw_value, dict):
        if raw_value.get("is_null") is True:
            if not column.nullable:
                raise ValueError(f"Column {column.name} không cho phép NULL.")
            return None
        value = raw_value.get("value", "")
    else:
        value = raw_value
    if value is None:
        if not column.nullable:
            raise ValueError(f"Column {column.name} không cho phép NULL.")
        return None
    text = str(value)
    type_name = column.normalized_type_name
    if type_name in {"bit", "boolean", "bool"}:
        normalized = text.strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
        raise ValueError(f"Giá trị boolean không hợp lệ cho {column.name}: {text}")
    integer_types = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint"}
    if type_name in integer_types:
        return int(text)
    decimal_markers = {"decimal", "numeric", "dec", "number", "money", "smallmoney", "float", "real", "double"}
    if type_name in decimal_markers or column.numeric_scale is not None:
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Giá trị numeric không hợp lệ cho {column.name}: {text}") from exc
    return text


def _find_negative_row(
    workspace: _Workspace,
    item_id: str,
    relation: dict[str, Any],
    connection,
    adapter: DatabaseAdapter,
    batch_size: int,
) -> tuple[list[object] | None, str]:
    metadata = _metadata_from_relation(relation)
    if metadata.relation_type != "table":
        return None, "Negative record chỉ hỗ trợ base table."
    primary_keys = [column for column in metadata.columns if column.is_primary_key]
    if not primary_keys:
        return None, "Table không có primary key để xác định complement."

    temp_table = f"matched_keys_{uuid.uuid4().hex}"
    with sqlite3.connect(workspace.sqlite_path) as spool:
        spool.execute(f"CREATE TEMP TABLE {temp_table} (key_hash TEXT PRIMARY KEY)")
        offset = 0
        while True:
            rows = _read_spool_rows(workspace.sqlite_path, item_id, offset, batch_size)
            if not rows:
                break
            keys = []
            for row in rows:
                values = _deserialize_row_payload(str(row["payload"]))
                keys.append((_pk_hash(values, metadata.columns),))
            spool.executemany(f"INSERT OR IGNORE INTO {temp_table}(key_hash) VALUES (?)", keys)
            offset += len(rows)

        cursor = connection.cursor()
        column_sql = ", ".join(adapter.quote_identifier(column.name) for column in metadata.columns)
        order_sql = ", ".join(adapter.quote_identifier(column.name) for column in primary_keys)
        sql = f"SELECT {column_sql} FROM {adapter.qualified_table(metadata)} ORDER BY {order_sql}"
        adapter.execute(cursor, sql)
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                values = list(row)
                key_hash = _pk_hash(values, metadata.columns)
                exists = spool.execute(f"SELECT 1 FROM {temp_table} WHERE key_hash = ?", (key_hash,)).fetchone()
                if exists is None:
                    return values, ""
    return None, "Không tìm thấy record âm hoặc toàn bộ table đều tham gia query."


def _pk_hash(values: Sequence[object], columns: list[DatabaseColumn]) -> str:
    payload = [
        {"name": column.name, "value": _serialize_value(values[index] if index < len(values) else None)}
        for index, column in enumerate(columns)
        if column.is_primary_key
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _unique_export_path(output_path: Path, source: dict[str, Any], relation: dict[str, Any]) -> Path:
    parts = [
        f"stmt{source.get('statement_index', 0)}",
        _safe_token(str(source.get("scope_id", ""))),
        _safe_token(str(relation.get("alias") or relation.get("name") or relation.get("relation_id"))),
        _safe_token(str(relation.get("name") or "source")),
    ]
    name = "_".join(part for part in parts if part).strip("_") or "source"
    candidate = output_path / f"{name}.csv"
    if not candidate.exists():
        return candidate
    for index in range(2, 10000):
        candidate = output_path / f"{name}_{index}.csv"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Không thể tạo tên file export không trùng cho {name}.")


def _safe_token(value: str) -> str:
    result = []
    for char in str(value):
        if char.isalnum() or char in {"_", "-"}:
            result.append(char)
        elif char in {".", " "}:
            result.append("_")
    token = "".join(result).strip("_")
    return token[:80] or "item"
