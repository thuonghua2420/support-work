from __future__ import annotations

import hashlib
import json
import pickle
import re
import tempfile
import time as time_module
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from heapq import heapify, heappop, heappush
from pathlib import Path
from typing import Callable, Iterable, Sequence, TypeVar

from .dbeaver_csv import (
    DbeaverCsv,
    TypedDbeaverCsvRowWriter,
    read_dbeaver_csv,
    write_dbeaver_csv,
    write_typed_dbeaver_csv_rows,
)

Logger = Callable[[str], None]
CancelChecker = Callable[[], None]
SYNC_PROGRESS_PREFIX = "__SYNC_PROGRESS__"


class OperationCancelledError(RuntimeError):
    """Raised when a long-running operation is cancelled by the web job manager."""


def _check_cancel(cancel: CancelChecker | None) -> None:
    if cancel is not None:
        cancel()

DATABASE_SQLSERVER = "sqlserver"
DATABASE_MYSQL = "mysql"
DATABASE_POSTGRESQL = "postgresql"
DATABASE_ORACLE = "oracle"

DATABASE_LABELS = {
    DATABASE_SQLSERVER: "SQL Server",
    DATABASE_MYSQL: "MySQL",
    DATABASE_POSTGRESQL: "PostgreSQL",
    DATABASE_ORACLE: "Oracle",
}

DEFAULT_PORTS = {
    DATABASE_SQLSERVER: "1433",
    DATABASE_MYSQL: "3306",
    DATABASE_POSTGRESQL: "5432",
    DATABASE_ORACLE: "1521",
}

DEFAULT_SCHEMAS = {
    DATABASE_SQLSERVER: "dbo",
    DATABASE_POSTGRESQL: "public",
}

SQLSERVER_ODBC_DRIVER_DEFAULT = "ODBC Driver 18 for SQL Server"
SQLSERVER_MODERN_DRIVER_KEYWORDS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver",
)
SQLSERVER_NATIVE_DRIVER_KEYWORDS = (
    "SQL Server Native Client RDA",
    "SQL Server Native Client",
    "SQL Server Native",
)
DATETIME_TYPE_NAMES = {
    "datetime",
    "datetime2",
    "smalldatetime",
    "datetimeoffset",
    "timestamp with time zone",
    "timestamp without time zone",
    "timestamp",
    "timestamp with local time zone",
}
TIME_TYPE_NAMES = {"time", "time with time zone", "time without time zone"}
TEXT_TYPE_NAMES = {
    "char",
    "character",
    "varchar",
    "character varying",
    "text",
    "nchar",
    "nvarchar",
    "ntext",
    "tinytext",
    "mediumtext",
    "longtext",
    "clob",
    "nclob",
    "xml",
    "json",
    "jsonb",
    "uuid",
    "uniqueidentifier",
}
DECIMAL_TYPE_NAMES = {
    "decimal",
    "numeric",
    "dec",
    "number",
    "money",
    "smallmoney",
    "float",
    "real",
    "double",
    "double precision",
    "binary_float",
    "binary_double",
}
INTEGER_TYPE_NAMES = {
    "bit",
    "tinyint",
    "smallint",
    "mediumint",
    "int",
    "integer",
    "bigint",
    "serial",
    "smallserial",
    "bigserial",
}
NON_INSERTABLE_TYPE_NAMES = {"rowversion"}
CSV_DECIMAL_QUANT = Decimal("0.0001")
IMPORT_MODE_APPEND = "append"
IMPORT_MODE_DELETE_MATCHING_KEYS = "delete_matching_keys"
IMPORT_MODE_TRUNCATE_TABLE = "truncate_table"
IMPORT_MODES = {
    IMPORT_MODE_APPEND,
    IMPORT_MODE_DELETE_MATCHING_KEYS,
    IMPORT_MODE_TRUNCATE_TABLE,
}
SYNC_MODE_APPEND = "append"
SYNC_MODE_INCREMENTAL = "incremental"
SYNC_MODE_TRUNCATE_TABLE = "truncate_table"
SYNC_MODE_CONDITION = "condition"
SYNC_MODES = {
    SYNC_MODE_APPEND,
    SYNC_MODE_INCREMENTAL,
    SYNC_MODE_TRUNCATE_TABLE,
    SYNC_MODE_CONDITION,
}
SYNC_DUPLICATE_ERROR = "error"
SYNC_DUPLICATE_DELETE_INSERT = "delete_insert"
SYNC_DUPLICATE_UPSERT = "upsert"
SYNC_DUPLICATE_MODES = {
    SYNC_DUPLICATE_ERROR,
    SYNC_DUPLICATE_DELETE_INSERT,
    SYNC_DUPLICATE_UPSERT,
}
DEFAULT_SYNC_BATCH_SIZE = 5000
MIN_SYNC_BATCH_SIZE = 100
MAX_SYNC_BATCH_SIZE = 100000


class TableNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class DatabaseConnectionSettings:
    database_type: str
    host: str
    database: str
    schema: str = ""
    port: str = ""
    username: str = ""
    password: str = ""
    trusted_connection: bool = False
    driver: str = SQLSERVER_ODBC_DRIVER_DEFAULT
    trust_server_certificate: bool = True
    encrypt: bool = False

    @property
    def normalized_type(self) -> str:
        return normalize_database_type(self.database_type)


@dataclass(frozen=True)
class DatabaseColumn:
    name: str
    ordinal: int
    data_type: str
    nullable: bool = True
    default_value: str | None = None
    is_identity: bool = False
    identity_generation: str = ""
    is_computed: bool = False
    generated_expression: str | None = None
    numeric_scale: int | None = None
    numeric_precision: int | None = None
    is_primary_key: bool = False

    @property
    def normalized_type_name(self) -> str:
        return self.data_type.lower()

    @property
    def is_generated(self) -> bool:
        return self.is_computed or bool(self.generated_expression)

    @property
    def is_rowversion(self) -> bool:
        return self.normalized_type_name in NON_INSERTABLE_TYPE_NAMES

    @property
    def is_datetime_export(self) -> bool:
        return self.normalized_type_name in DATETIME_TYPE_NAMES

    @property
    def is_time_export(self) -> bool:
        return self.normalized_type_name in TIME_TYPE_NAMES

    @property
    def is_decimal_export(self) -> bool:
        return self.normalized_type_name in DECIMAL_TYPE_NAMES or (
            self.numeric_scale is not None and self.numeric_scale > 0
        )

    @property
    def is_number_export(self) -> bool:
        return self.is_decimal_export or self.normalized_type_name in INTEGER_TYPE_NAMES

    @property
    def should_quote_export(self) -> bool:
        return self.normalized_type_name in TEXT_TYPE_NAMES


@dataclass(frozen=True)
class TableMetadata:
    schema: str
    name: str
    columns: list[DatabaseColumn]
    relation_type: str = "table"


@dataclass(frozen=True)
class ForeignKeyEdge:
    child_schema: str
    child_table: str
    parent_schema: str
    parent_table: str
    constraint_name: str

    @property
    def child(self) -> tuple[str, str]:
        return self.child_schema, self.child_table

    @property
    def parent(self) -> tuple[str, str]:
        return self.parent_schema, self.parent_table


_TableKey = tuple[str, str]
_TableName = TypeVar("_TableName", str, _TableKey)
_ImportTables = dict[_TableKey, list[tuple[Path, TableMetadata]]]


@dataclass(frozen=True)
class CsvDbResult:
    csv_path: Path
    table_name: str
    row_count: int
    skipped_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class CsvTableCandidate:
    csv_path: Path
    table_name: str
    row_count: int
    has_header: bool


@dataclass(frozen=True)
class DatabaseSyncResult:
    table_name: str
    row_count: int
    skipped_columns: tuple[str, ...] = ()
    source_row_count: int = 0
    target_row_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    unchanged_count: int = 0
    retained_target_only_count: int = 0
    backup_row_count: int = 0


@dataclass(frozen=True)
class DatabaseCsvSuccess:
    table: str
    row_count: int


@dataclass(frozen=True)
class DatabaseCsvIssue:
    table: str
    message: str


@dataclass
class DatabaseCsvSummary:
    action_name: str
    root_path: Path
    csv_results: list[CsvDbResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    succeeded: list[DatabaseCsvSuccess] = field(default_factory=list)
    failed: list[DatabaseCsvIssue] = field(default_factory=list)
    skipped_items: list[DatabaseCsvIssue] = field(default_factory=list)

    @property
    def csv_count(self) -> int:
        return len(self.csv_results)

    @property
    def row_count(self) -> int:
        return sum(result.row_count for result in self.csv_results)

    @property
    def error_count(self) -> int:
        return len(self.errors)


@dataclass
class DatabaseSyncSummary:
    action_name: str = "Đồng bộ dữ liệu giữa 2 CSDL"
    table_results: list[DatabaseSyncResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    backup_path: Path | None = None

    @property
    def table_count(self) -> int:
        return len(self.table_results)

    @property
    def row_count(self) -> int:
        return sum(result.row_count for result in self.table_results)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def inserted_count(self) -> int:
        return sum(result.inserted_count for result in self.table_results)

    @property
    def updated_count(self) -> int:
        return sum(result.updated_count for result in self.table_results)

    @property
    def deleted_count(self) -> int:
        return sum(result.deleted_count for result in self.table_results)

    @property
    def unchanged_count(self) -> int:
        return sum(result.unchanged_count for result in self.table_results)

    @property
    def source_row_count(self) -> int:
        return sum(result.source_row_count for result in self.table_results)

    @property
    def target_row_count(self) -> int:
        return sum(result.target_row_count for result in self.table_results)

    @property
    def retained_target_only_count(self) -> int:
        return sum(result.retained_target_only_count for result in self.table_results)

    @property
    def backup_row_count(self) -> int:
        return sum(result.backup_row_count for result in self.table_results)


@dataclass(frozen=True)
class CsvColumnMapping:
    csv_index_by_db_name: dict[str, int]
    columns: list[DatabaseColumn]
    skipped_columns: tuple[str, ...] = ()


class DatabaseAdapter:
    transactional_truncate = True

    def connect(self, settings: DatabaseConnectionSettings):
        raise NotImplementedError

    def test_sql(self) -> str:
        return "SELECT 1"

    def stream_cursor(self, connection):
        return connection.cursor()

    def execute(self, cursor, sql: str, params: Sequence[object] = ()) -> None:
        cursor.execute(sql, tuple(params))

    def executemany(self, cursor, sql: str, rows: Sequence[Sequence[object]]) -> None:
        cursor.executemany(sql, rows)

    def placeholder(self, index: int) -> str:
        return "?"

    def quote_identifier(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def default_schema(self, settings: DatabaseConnectionSettings) -> str:
        return DEFAULT_SCHEMAS.get(settings.normalized_type, settings.schema)

    def schema_name(self, settings: DatabaseConnectionSettings, schema: str | None = None) -> str:
        selected_schema = (schema if schema is not None else settings.schema).strip()
        return selected_schema or self.default_schema(settings)

    def qualified_table(self, metadata: TableMetadata) -> str:
        return f"{self.quote_identifier(metadata.schema)}.{self.quote_identifier(metadata.name)}"

    def list_databases(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        return [settings.database] if settings.database else []

    def list_tables(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        raise NotImplementedError

    def list_foreign_keys(self, connection, settings: DatabaseConnectionSettings) -> list[ForeignKeyEdge]:
        return []

    def _query_foreign_keys(self, connection, sql: str, params: Sequence[object] = ()) -> list[ForeignKeyEdge]:
        cursor = connection.cursor()
        try:
            self.execute(cursor, sql, params)
            return [ForeignKeyEdge(*row) for row in cursor.fetchall()]
        finally:
            _close_cursor(cursor)

    def get_table(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        table_name: str,
        schema: str | None = None,
    ) -> TableMetadata:
        raise NotImplementedError

    def find_view(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        view_name: str,
        schema: str | None = None,
    ) -> tuple[str, str] | None:
        return None

    def get_relation(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        relation_name: str,
        schema: str | None = None,
    ) -> TableMetadata:
        try:
            return self.get_table(connection, settings, relation_name, schema)
        except TableNotFoundError as table_error:
            view = self.find_view(connection, settings, relation_name, schema)
            if view is None:
                raise table_error
            view_schema, actual_name = view
            metadata = TableMetadata(schema=view_schema, name=actual_name, columns=[], relation_type="view")
            cursor = connection.cursor()
            self.execute(cursor, f"SELECT * FROM {self.qualified_table(metadata)} WHERE 1 = 0")
            description = cursor.description or []
            columns = [
                DatabaseColumn(
                    name=str(item[0]),
                    ordinal=index,
                    data_type=_description_type_name(item),
                    nullable=_description_nullable(item),
                )
                for index, item in enumerate(description, start=1)
            ]
            return TableMetadata(
                schema=view_schema,
                name=actual_name,
                columns=columns,
                relation_type="view",
            )

    def insert_sql(
        self,
        metadata: TableMetadata,
        columns: list[DatabaseColumn],
        keep_identity: bool,
    ) -> str:
        column_sql = ", ".join(self.quote_identifier(column.name) for column in columns)
        placeholder_sql = ", ".join(self.placeholder(index) for index, _column in enumerate(columns))
        return f"INSERT INTO {self.qualified_table(metadata)} ({column_sql}) VALUES ({placeholder_sql})"

    def truncate_table(self, cursor, metadata: TableMetadata) -> None:
        self.execute(cursor, f"TRUNCATE TABLE {self.qualified_table(metadata)}")

    def validate_import_clear(self, cursor, tables: Sequence[TableMetadata]) -> None:
        return None

    def before_import(
        self,
        cursor,
        metadata: TableMetadata,
        columns: list[DatabaseColumn],
        keep_identity: bool,
    ) -> None:
        return None

    def after_import(
        self,
        cursor,
        metadata: TableMetadata,
        columns: list[DatabaseColumn],
        keep_identity: bool,
    ) -> None:
        return None

    def can_keep_identity(self, column: DatabaseColumn) -> bool:
        return True


class SqlServerAdapter(DatabaseAdapter):
    def connect(self, settings: DatabaseConnectionSettings):
        try:
            import pyodbc
        except ImportError as exc:
            raise RuntimeError("Chưa cài pyodbc. Hãy chạy run.bat để cài thư viện kết nối SQL Server.") from exc

        parts = _build_sqlserver_connection_parts(settings)
        return pyodbc.connect(";".join(parts), autocommit=False)

    def execute(self, cursor, sql: str, params: Sequence[object] = ()) -> None:
        cursor.execute(sql, *params)

    def quote_identifier(self, value: str) -> str:
        return "[" + value.replace("]", "]]") + "]"

    def default_schema(self, settings: DatabaseConnectionSettings) -> str:
        return settings.schema.strip() or "dbo"

    def list_foreign_keys(self, connection, settings: DatabaseConnectionSettings) -> list[ForeignKeyEdge]:
        return self._query_foreign_keys(
            connection,
            """
            SELECT DISTINCT child_schema.name, child.name, parent_schema.name, parent.name, fk.name
            FROM sys.foreign_keys fk
            INNER JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
            INNER JOIN sys.tables child ON child.object_id = fkc.parent_object_id
            INNER JOIN sys.schemas child_schema ON child_schema.schema_id = child.schema_id
            INNER JOIN sys.tables parent ON parent.object_id = fkc.referenced_object_id
            INNER JOIN sys.schemas parent_schema ON parent_schema.schema_id = parent.schema_id
            """,
        )

    def list_databases(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT name
            FROM sys.databases
            WHERE state = 0
            ORDER BY name
            """,
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def list_tables(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        schema = self.schema_name(settings)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT tb.name
            FROM sys.schemas s
            INNER JOIN sys.tables tb ON tb.schema_id = s.schema_id
            WHERE s.name = ?
            ORDER BY tb.name
            """,
            (schema,),
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def find_view(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        view_name: str,
        schema: str | None = None,
    ) -> tuple[str, str] | None:
        selected_schema = self.schema_name(settings, schema)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT TOP (1) s.name, v.name
            FROM sys.schemas s
            INNER JOIN sys.views v ON v.schema_id = s.schema_id
            WHERE s.name = ? AND LOWER(v.name) = LOWER(?)
            ORDER BY CASE WHEN v.name = ? THEN 0 ELSE 1 END, v.name
            """,
            (selected_schema, view_name, view_name),
        )
        row = cursor.fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    def get_table(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        table_name: str,
        schema: str | None = None,
    ) -> TableMetadata:
        selected_schema = self.schema_name(settings, schema)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT TOP (1) s.name, tb.name, tb.object_id
            FROM sys.schemas s
            INNER JOIN sys.tables tb ON tb.schema_id = s.schema_id
            WHERE s.name = ? AND (tb.name = ? OR LOWER(tb.name) = LOWER(?))
            ORDER BY CASE WHEN tb.name = ? THEN 0 ELSE 1 END, tb.name
            """,
            (selected_schema, table_name, table_name, table_name),
        )
        table_row = cursor.fetchone()
        if table_row is None:
            raise TableNotFoundError(f"Không tìm thấy table: {selected_schema}.{table_name}")

        object_id = table_row[2]
        self.execute(
            cursor,
            """
            SELECT
                c.name,
                c.column_id,
                c.is_nullable,
                CONVERT(nvarchar(max), dc.definition) AS default_value,
                c.is_identity,
                c.is_computed,
                c.generated_always_type,
                ty.name AS type_name,
                TYPE_NAME(c.system_type_id) AS system_type_name,
                c.scale,
                c.precision,
                CASE WHEN pk.column_id IS NULL THEN CONVERT(bit, 0) ELSE CONVERT(bit, 1) END AS is_primary_key
            FROM sys.columns c
            INNER JOIN sys.types ty ON ty.user_type_id = c.user_type_id
            LEFT JOIN sys.default_constraints dc
                ON dc.object_id = c.default_object_id
            LEFT JOIN (
                SELECT ic.object_id, ic.column_id
                FROM sys.indexes i
                INNER JOIN sys.index_columns ic
                    ON ic.object_id = i.object_id
                   AND ic.index_id = i.index_id
                WHERE i.is_primary_key = 1
            ) pk
                ON pk.object_id = c.object_id
               AND pk.column_id = c.column_id
            WHERE c.object_id = ?
            ORDER BY c.column_id
            """,
            (object_id,),
        )
        columns = [
            DatabaseColumn(
                name=str(row[0]),
                ordinal=int(row[1]),
                nullable=bool(row[2]),
                default_value=row[3],
                is_identity=bool(row[4]),
                is_computed=bool(row[5]),
                identity_generation="IDENTITY" if bool(row[4]) else "",
                generated_expression="GENERATED_ALWAYS" if int(row[6]) else None,
                data_type=_sqlserver_type_name(row[8] or row[7]),
                numeric_scale=_optional_int(row[9]),
                numeric_precision=_optional_int(row[10]),
                is_primary_key=bool(row[11]),
            )
            for row in cursor.fetchall()
        ]
        return TableMetadata(schema=str(table_row[0]), name=str(table_row[1]), columns=columns)

    def before_import(
        self,
        cursor,
        metadata: TableMetadata,
        columns: list[DatabaseColumn],
        keep_identity: bool,
    ) -> None:
        if keep_identity and any(column.is_identity for column in columns):
            self.execute(cursor, f"SET IDENTITY_INSERT {self.qualified_table(metadata)} ON")

    def after_import(
        self,
        cursor,
        metadata: TableMetadata,
        columns: list[DatabaseColumn],
        keep_identity: bool,
    ) -> None:
        if keep_identity and any(column.is_identity for column in columns):
            self.execute(cursor, f"SET IDENTITY_INSERT {self.qualified_table(metadata)} OFF")


def _build_sqlserver_connection_parts(settings: DatabaseConnectionSettings) -> list[str]:
    parts = [
        f"DRIVER={_brace_value(settings.driver)}",
        f"SERVER={_brace_value(_server_with_port(settings.host, settings.port))}",
        f"DATABASE={_brace_value(settings.database)}",
    ]
    if is_modern_sqlserver_odbc_driver(settings.driver):
        parts.append(f"Encrypt={'yes' if settings.encrypt else 'no'}")
        parts.append(f"TrustServerCertificate={'yes' if settings.trust_server_certificate else 'no'}")
    if settings.trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={_brace_value(settings.username)}")
        parts.append(f"PWD={_brace_value(settings.password)}")
    return parts


class MySqlAdapter(DatabaseAdapter):
    transactional_truncate = False

    def connect(self, settings: DatabaseConnectionSettings):
        try:
            import mysql.connector
        except ImportError as exc:
            raise RuntimeError("Chưa cài mysql-connector-python. Hãy chạy run.bat để cài thư viện MySQL.") from exc

        return mysql.connector.connect(
            host=settings.host,
            port=int(settings.port or DEFAULT_PORTS[DATABASE_MYSQL]),
            database=settings.database or None,
            user=settings.username,
            password=settings.password,
            autocommit=False,
        )

    def placeholder(self, index: int) -> str:
        return "%s"

    def stream_cursor(self, connection):
        return connection.cursor(buffered=False)

    def quote_identifier(self, value: str) -> str:
        return "`" + value.replace("`", "``") + "`"

    def default_schema(self, settings: DatabaseConnectionSettings) -> str:
        return settings.schema.strip() or settings.database

    def list_foreign_keys(self, connection, settings: DatabaseConnectionSettings) -> list[ForeignKeyEdge]:
        return self._query_foreign_keys(
            connection,
            """
            SELECT DISTINCT TABLE_SCHEMA, TABLE_NAME, REFERENCED_TABLE_SCHEMA,
                            REFERENCED_TABLE_NAME, CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE REFERENCED_TABLE_NAME IS NOT NULL
              AND TABLE_SCHEMA = %s AND REFERENCED_TABLE_SCHEMA = TABLE_SCHEMA
            """,
            (settings.database,),
        )

    def validate_import_clear(self, cursor, tables: Sequence[TableMetadata]) -> None:
        # DELETE can be rolled back only on a transactional MySQL storage engine.
        for schema in sorted({table.schema for table in tables}):
            self.execute(
                cursor,
                """
                SELECT t.TABLE_NAME
                FROM information_schema.TABLES t
                INNER JOIN information_schema.ENGINES e ON e.ENGINE = t.ENGINE
                WHERE t.TABLE_SCHEMA = %s AND e.TRANSACTIONS = 'YES'
                """,
                (schema,),
            )
            transactional = {row[0] for row in cursor.fetchall()}
            unsupported = [
                f"{table.schema}.{table.name}" for table in tables
                if table.schema == schema and table.name not in transactional
            ]
            if unsupported:
                raise ValueError("Không thể rollback thao tác xóa trên các table: " + ", ".join(unsupported))

    def list_databases(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT schema_name
            FROM information_schema.schemata
            ORDER BY schema_name
            """,
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def list_tables(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        schema = self.schema_name(settings)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def find_view(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        view_name: str,
        schema: str | None = None,
    ) -> tuple[str, str] | None:
        selected_schema = self.schema_name(settings, schema)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND LOWER(table_name) = LOWER(%s) AND table_type = 'VIEW'
            ORDER BY CASE WHEN table_name = %s THEN 0 ELSE 1 END, table_name
            LIMIT 1
            """,
            (selected_schema, view_name, view_name),
        )
        row = cursor.fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    def get_table(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        table_name: str,
        schema: str | None = None,
    ) -> TableMetadata:
        selected_schema = self.schema_name(settings, schema)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND LOWER(table_name) = LOWER(%s) AND table_type = 'BASE TABLE'
            ORDER BY CASE WHEN table_name = %s THEN 0 ELSE 1 END, table_name
            LIMIT 1
            """,
            (selected_schema, table_name, table_name),
        )
        table_row = cursor.fetchone()
        if table_row is None:
            raise TableNotFoundError(f"Không tìm thấy table: {selected_schema}.{table_name}")

        self.execute(
            cursor,
            """
            SELECT
                c.column_name,
                c.ordinal_position,
                c.is_nullable,
                c.column_default,
                c.extra,
                c.data_type,
                c.generation_expression,
                c.numeric_scale,
                c.numeric_precision,
                CASE WHEN c.column_key = 'PRI' THEN 1 ELSE 0 END AS is_primary_key
            FROM information_schema.columns c
            WHERE c.table_schema = %s AND c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            (table_row[0], table_row[1]),
        )
        columns = []
        for row in cursor.fetchall():
            extra = str(row[4] or "").lower()
            generation_expression = row[6]
            columns.append(
                DatabaseColumn(
                    name=str(row[0]),
                    ordinal=int(row[1]),
                    nullable=str(row[2]).upper() == "YES",
                    default_value=row[3],
                    is_identity="auto_increment" in extra,
                    identity_generation="AUTO_INCREMENT" if "auto_increment" in extra else "",
                    is_computed="generated" in extra or bool(generation_expression),
                    generated_expression=generation_expression,
                    data_type=str(row[5]),
                    numeric_scale=_optional_int(row[7]),
                    numeric_precision=_optional_int(row[8]),
                    is_primary_key=bool(row[9]),
                )
            )
        return TableMetadata(schema=str(table_row[0]), name=str(table_row[1]), columns=columns)


class PostgreSqlAdapter(DatabaseAdapter):
    def connect(self, settings: DatabaseConnectionSettings):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Chưa cài psycopg. Hãy chạy run.bat để cài thư viện PostgreSQL.") from exc

        return psycopg.connect(
            host=settings.host,
            port=int(settings.port or DEFAULT_PORTS[DATABASE_POSTGRESQL]),
            dbname=settings.database,
            user=settings.username,
            password=settings.password,
        )

    def placeholder(self, index: int) -> str:
        return "%s"

    def stream_cursor(self, connection):
        return connection.cursor(name="autocompare_sync_stream")

    def list_foreign_keys(self, connection, settings: DatabaseConnectionSettings) -> list[ForeignKeyEdge]:
        return self._query_foreign_keys(
            connection,
            """
            SELECT child_schema.nspname, child.relname, parent_schema.nspname, parent.relname, fk.conname
            FROM pg_catalog.pg_constraint fk
            INNER JOIN pg_catalog.pg_class child ON child.oid = fk.conrelid
            INNER JOIN pg_catalog.pg_namespace child_schema ON child_schema.oid = child.relnamespace
            INNER JOIN pg_catalog.pg_class parent ON parent.oid = fk.confrelid
            INNER JOIN pg_catalog.pg_namespace parent_schema ON parent_schema.oid = parent.relnamespace
            WHERE fk.contype = 'f'
            """,
        )

    def list_databases(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT datname
            FROM pg_database
            WHERE datallowconn = true
            ORDER BY datname
            """,
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def list_tables(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        schema = self.schema_name(settings)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def find_view(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        view_name: str,
        schema: str | None = None,
    ) -> tuple[str, str] | None:
        selected_schema = self.schema_name(settings, schema)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT table_schema, table_name
            FROM information_schema.views
            WHERE table_schema = %s AND LOWER(table_name) = LOWER(%s)
            ORDER BY CASE WHEN table_name = %s THEN 0 ELSE 1 END, table_name
            LIMIT 1
            """,
            (selected_schema, view_name, view_name),
        )
        row = cursor.fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    def get_table(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        table_name: str,
        schema: str | None = None,
    ) -> TableMetadata:
        selected_schema = self.schema_name(settings, schema)
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND LOWER(table_name) = LOWER(%s) AND table_type = 'BASE TABLE'
            ORDER BY CASE WHEN table_name = %s THEN 0 ELSE 1 END, table_name
            LIMIT 1
            """,
            (selected_schema, table_name, table_name),
        )
        table_row = cursor.fetchone()
        if table_row is None:
            raise TableNotFoundError(f"Không tìm thấy table: {selected_schema}.{table_name}")

        self.execute(
            cursor,
            """
            SELECT
                c.column_name,
                c.ordinal_position,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.is_identity,
                c.identity_generation,
                c.is_generated,
                c.generation_expression,
                c.numeric_scale,
                c.numeric_precision,
                CASE WHEN kcu.column_name IS NULL THEN false ELSE true END AS is_primary_key
            FROM information_schema.columns c
            LEFT JOIN information_schema.key_column_usage kcu
                ON kcu.table_schema = c.table_schema
               AND kcu.table_name = c.table_name
               AND kcu.column_name = c.column_name
               AND kcu.constraint_name IN (
                    SELECT tc.constraint_name
                    FROM information_schema.table_constraints tc
                    WHERE tc.table_schema = c.table_schema
                      AND tc.table_name = c.table_name
                      AND tc.constraint_type = 'PRIMARY KEY'
               )
            WHERE c.table_schema = %s AND c.table_name = %s
            ORDER BY c.ordinal_position
            """,
            (table_row[0], table_row[1]),
        )
        columns = [
            DatabaseColumn(
                name=str(row[0]),
                ordinal=int(row[1]),
                data_type=str(row[2]),
                nullable=str(row[3]).upper() == "YES",
                default_value=row[4],
                is_identity=str(row[5]).upper() == "YES",
                identity_generation=str(row[6] or ""),
                is_computed=str(row[7]).upper() == "ALWAYS",
                generated_expression=row[8],
                numeric_scale=_optional_int(row[9]),
                numeric_precision=_optional_int(row[10]),
                is_primary_key=bool(row[11]),
            )
            for row in cursor.fetchall()
        ]
        return TableMetadata(schema=str(table_row[0]), name=str(table_row[1]), columns=columns)

    def insert_sql(
        self,
        metadata: TableMetadata,
        columns: list[DatabaseColumn],
        keep_identity: bool,
    ) -> str:
        column_sql = ", ".join(self.quote_identifier(column.name) for column in columns)
        placeholder_sql = ", ".join(self.placeholder(index) for index, _column in enumerate(columns))
        override_clause = " OVERRIDING SYSTEM VALUE" if keep_identity and any(column.is_identity for column in columns) else ""
        return f"INSERT INTO {self.qualified_table(metadata)} ({column_sql}){override_clause} VALUES ({placeholder_sql})"


class OracleAdapter(DatabaseAdapter):
    transactional_truncate = False

    def connect(self, settings: DatabaseConnectionSettings):
        try:
            import oracledb
        except ImportError as exc:
            raise RuntimeError("Chưa cài oracledb. Hãy chạy run.bat để cài thư viện Oracle.") from exc

        if settings.host:
            dsn = oracledb.makedsn(
                settings.host,
                int(settings.port or DEFAULT_PORTS[DATABASE_ORACLE]),
                service_name=settings.database,
            )
        else:
            dsn = settings.database
        return oracledb.connect(user=settings.username, password=settings.password, dsn=dsn)

    def test_sql(self) -> str:
        return "SELECT 1 FROM dual"

    def placeholder(self, index: int) -> str:
        return f":{index + 1}"

    def default_schema(self, settings: DatabaseConnectionSettings) -> str:
        return (settings.schema.strip() or settings.username).upper()

    def list_foreign_keys(self, connection, settings: DatabaseConnectionSettings) -> list[ForeignKeyEdge]:
        return self._query_foreign_keys(
            connection,
            """
            SELECT child.owner, child.table_name, parent.owner, parent.table_name, child.constraint_name
            FROM all_constraints child
            INNER JOIN all_constraints parent
                ON parent.owner = child.r_owner AND parent.constraint_name = child.r_constraint_name
            WHERE child.constraint_type = 'R'
            """,
        )

    def list_tables(self, connection, settings: DatabaseConnectionSettings) -> list[str]:
        schema = self.schema_name(settings).upper()
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT table_name
            FROM all_tables
            WHERE owner = :1
            ORDER BY table_name
            """,
            (schema,),
        )
        return [str(row[0]) for row in cursor.fetchall()]

    def find_view(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        view_name: str,
        schema: str | None = None,
    ) -> tuple[str, str] | None:
        selected_schema = self.schema_name(settings, schema).upper()
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT owner, view_name
            FROM all_views
            WHERE owner = :1 AND LOWER(view_name) = LOWER(:2)
            ORDER BY CASE WHEN view_name = :3 THEN 0 ELSE 1 END, view_name
            FETCH FIRST 1 ROWS ONLY
            """,
            (selected_schema, view_name, view_name),
        )
        row = cursor.fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    def get_table(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        table_name: str,
        schema: str | None = None,
    ) -> TableMetadata:
        selected_schema = self.schema_name(settings, schema).upper()
        cursor = connection.cursor()
        self.execute(
            cursor,
            """
            SELECT owner, table_name
            FROM all_tables
            WHERE owner = :1 AND LOWER(table_name) = LOWER(:2)
            ORDER BY CASE WHEN table_name = :3 THEN 0 ELSE 1 END, table_name
            FETCH FIRST 1 ROWS ONLY
            """,
            (selected_schema, table_name, table_name),
        )
        table_row = cursor.fetchone()
        if table_row is None:
            raise TableNotFoundError(f"Không tìm thấy table: {selected_schema}.{table_name}")

        self.execute(
            cursor,
            """
            SELECT
                c.column_name,
                c.column_id,
                c.data_type,
                c.nullable,
                NULL AS data_default,
                c.virtual_column,
                c.identity_column,
                ic.generation_type,
                c.data_scale,
                c.data_precision,
                CASE WHEN pk.column_name IS NULL THEN 0 ELSE 1 END AS is_primary_key
            FROM all_tab_cols c
            LEFT JOIN all_tab_identity_cols ic
                ON ic.owner = c.owner
               AND ic.table_name = c.table_name
               AND ic.column_name = c.column_name
            LEFT JOIN (
                SELECT acc.owner, acc.table_name, acc.column_name
                FROM all_constraints ac
                INNER JOIN all_cons_columns acc
                    ON acc.owner = ac.owner
                   AND acc.constraint_name = ac.constraint_name
                   AND acc.table_name = ac.table_name
                WHERE ac.constraint_type = 'P'
            ) pk
                ON pk.owner = c.owner
               AND pk.table_name = c.table_name
               AND pk.column_name = c.column_name
            WHERE c.owner = :1
              AND c.table_name = :2
              AND c.hidden_column = 'NO'
            ORDER BY c.column_id
            """,
            (table_row[0], table_row[1]),
        )
        columns = [
            DatabaseColumn(
                name=str(row[0]),
                ordinal=int(row[1]),
                data_type=str(row[2]),
                nullable=str(row[3]).upper() == "Y",
                default_value=row[4],
                is_identity=str(row[6]).upper() == "YES",
                identity_generation=str(row[7] or ""),
                is_computed=str(row[5]).upper() == "YES",
                generated_expression="VIRTUAL" if str(row[5]).upper() == "YES" else None,
                numeric_scale=_optional_int(row[8]),
                numeric_precision=_optional_int(row[9]),
                is_primary_key=bool(row[10]),
            )
            for row in cursor.fetchall()
        ]
        return TableMetadata(schema=str(table_row[0]), name=str(table_row[1]), columns=columns)

    def can_keep_identity(self, column: DatabaseColumn) -> bool:
        return column.identity_generation.upper() != "ALWAYS"


def database_type_options() -> list[str]:
    return list(DATABASE_LABELS.values())


def database_sqlglot_dialect(database_type: str) -> str:
    return {
        DATABASE_SQLSERVER: "tsql",
        DATABASE_MYSQL: "mysql",
        DATABASE_POSTGRESQL: "postgres",
        DATABASE_ORACLE: "oracle",
    }[normalize_database_type(database_type)]


def normalize_database_type(value: str) -> str:
    normalized = value.strip().casefold().replace(" ", "")
    aliases = {
        "sqlserver": DATABASE_SQLSERVER,
        "mssql": DATABASE_SQLSERVER,
        "sql": DATABASE_SQLSERVER,
        "mysql": DATABASE_MYSQL,
        "postgres": DATABASE_POSTGRESQL,
        "postgresql": DATABASE_POSTGRESQL,
        "postgress": DATABASE_POSTGRESQL,
        "oracle": DATABASE_ORACLE,
        "oracel": DATABASE_ORACLE,
    }
    if normalized in aliases:
        return aliases[normalized]
    for key, label in DATABASE_LABELS.items():
        if normalized == label.casefold().replace(" ", ""):
            return key
    raise ValueError(f"Loại database chưa được hỗ trợ: {value}")


def database_label(database_type: str) -> str:
    return DATABASE_LABELS.get(normalize_database_type(database_type), database_type)


def default_port(database_type: str) -> str:
    return DEFAULT_PORTS.get(normalize_database_type(database_type), "")


def default_schema(database_type: str) -> str:
    normalized = normalize_database_type(database_type)
    return DEFAULT_SCHEMAS.get(normalized, "")


def get_available_sqlserver_drivers() -> list[str]:
    try:
        import pyodbc
    except ImportError:
        return []
    return list(pyodbc.drivers())


def is_sqlserver_native_client_driver(driver: str) -> bool:
    value = str(driver or "").lower()
    return any(keyword.lower() in value for keyword in SQLSERVER_NATIVE_DRIVER_KEYWORDS)


def is_modern_sqlserver_odbc_driver(driver: str) -> bool:
    value = str(driver or "").lower()
    return "odbc driver" in value and "sql server" in value


def preferred_sqlserver_driver(drivers: Sequence[str] | None = None) -> str:
    choices = [str(driver) for driver in (drivers or []) if str(driver).strip()]
    for keyword in SQLSERVER_MODERN_DRIVER_KEYWORDS:
        match = next((driver for driver in choices if keyword.lower() in driver.lower()), None)
        if match:
            return match
    native_match = next((driver for driver in choices if is_sqlserver_native_client_driver(driver)), None)
    if native_match:
        return native_match
    if choices:
        return choices[0]
    return SQLSERVER_ODBC_DRIVER_DEFAULT


def test_database_connection(settings: DatabaseConnectionSettings) -> None:
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    connection = adapter.connect(settings)
    try:
        cursor = connection.cursor()
        adapter.execute(cursor, adapter.test_sql())
        cursor.fetchone()
    finally:
        connection.close()


def list_database_names(settings: DatabaseConnectionSettings) -> list[str]:
    settings = validate_database_listing_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    connection = adapter.connect(settings)
    try:
        return adapter.list_databases(connection, settings)
    finally:
        connection.close()


def list_database_tables(settings: DatabaseConnectionSettings) -> list[str]:
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    connection = adapter.connect(settings)
    try:
        return adapter.list_tables(connection, settings)
    finally:
        connection.close()


def get_database_relation(
    settings: DatabaseConnectionSettings,
    relation_name: str,
    schema: str | None = None,
) -> TableMetadata:
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    connection = adapter.connect(settings)
    try:
        return adapter.get_relation(connection, settings, relation_name, schema)
    finally:
        connection.close()


def format_database_value(value: object, column: DatabaseColumn) -> str | None:
    return _format_db_value(value, column)


def apply_query_timeout(cursor, timeout_seconds: int) -> None:
    if timeout_seconds <= 0 or not hasattr(cursor, "timeout"):
        return
    try:
        cursor.timeout = int(timeout_seconds)
    except (AttributeError, TypeError, ValueError):
        return


def build_update_by_primary_key_sql(
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    update_columns: list[DatabaseColumn],
    primary_key_columns: list[DatabaseColumn],
) -> str:
    sql = _build_sync_update_sql(adapter, metadata, update_columns, primary_key_columns)
    if sql is None:
        raise ValueError("Cần ít nhất một column để update.")
    return sql


def canonical_row_hash(values: Sequence[object], columns: list[DatabaseColumn]) -> str:
    payload = [
        {"name": column.name, "value": _canonical_hash_value(values[index] if index < len(values) else None, column)}
        for index, column in enumerate(columns)
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def normalize_csv_folder(
    root_path: str | Path,
    settings: DatabaseConnectionSettings,
    log: Logger | None = None,
    cancel: CancelChecker | None = None,
) -> DatabaseCsvSummary:
    root = _validate_folder(root_path, must_exist=True)
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    logger = log or (lambda message: None)
    summary = DatabaseCsvSummary(action_name="Chuẩn hóa CSV theo CSDL", root_path=root)

    connection = adapter.connect(settings)
    try:
        for csv_path in _iter_csv_files(root):
            _check_cancel(cancel)
            _normalize_one_csv(connection, adapter, settings, root, csv_path, summary, logger, cancel)
    finally:
        connection.close()

    _log_summary(summary, logger)
    return summary


def scan_import_csv_tables(root_path: str | Path) -> list[CsvTableCandidate]:
    root = _validate_folder(root_path, must_exist=True)
    candidates: list[CsvTableCandidate] = []
    for csv_path in _iter_direct_csv_files(root):
        table = read_dbeaver_csv(csv_path)
        candidates.append(
            CsvTableCandidate(
                csv_path=csv_path,
                table_name=csv_path.stem,
                row_count=len(table.rows),
                has_header=bool(table.headers),
            )
        )
    return candidates


def order_tables_by_dependency(
    tables: Iterable[_TableName],
    edges: Iterable[ForeignKeyEdge],
) -> tuple[list[_TableName], list[list[_TableName]]]:
    """Return parents before children and report each cyclic component separately.

    Use (schema, table) pairs to distinguish tables in different schemas. String
    names may be qualified or unqualified when the scope is a single schema.
    """
    names: dict[tuple[str, ...], _TableName] = {}
    for table in tables:
        parts = (table,) if isinstance(table, str) else table
        names.setdefault(tuple(part.casefold() for part in parts), table)

    def find_key(table: _TableKey) -> tuple[str, ...]:
        schema, name = _fk_table_key(table)
        for key in ((schema, name), (f"{schema}.{name}",), (name,)):
            if key in names:
                return key
        return schema, name

    parents: dict[tuple[str, ...], set[tuple[str, ...]]] = {key: set() for key in names}
    children: dict[tuple[str, ...], set[tuple[str, ...]]] = {key: set() for key in names}
    for edge in edges:
        child, parent = find_key(edge.child), find_key(edge.parent)
        if child in names and parent in names and child != parent:
            parents[child].add(parent)
            children[parent].add(child)

    cycles = _dependency_cycles(parents, children)
    cyclic_keys = {key for cycle in cycles for key in cycle}
    remaining = {key: len(dependencies - cyclic_keys) for key, dependencies in parents.items() if key not in cyclic_keys}
    ready = [key for key, count in remaining.items() if count == 0]
    heapify(ready)
    ordered = []
    while ready:
        parent = heappop(ready)
        ordered.append(names[parent])
        for child in children[parent] - cyclic_keys:
            remaining[child] -= 1
            if remaining[child] == 0:
                heappush(ready, child)
    return ordered, [[names[key] for key in cycle] for cycle in cycles]


def _dependency_cycles(
    parents: dict[tuple[str, ...], set[tuple[str, ...]]],
    children: dict[tuple[str, ...], set[tuple[str, ...]]],
) -> list[list[tuple[str, ...]]]:
    # Find strongly connected components without recursing through long FK chains.
    finished = []
    visited = set()
    for key in parents:
        if key in visited:
            continue
        visited.add(key)
        stack = [(key, iter(children[key]))]
        while stack:
            current, neighbors = stack[-1]
            child = next(neighbors, None)
            if child is None:
                stack.pop()
                finished.append(current)
            elif child not in visited:
                visited.add(child)
                stack.append((child, iter(children[child])))

    cycles = []
    visited.clear()
    for key in reversed(finished):
        if key in visited:
            continue
        component = [key]
        visited.add(key)
        for current in component:
            unseen = parents[current] - visited
            visited.update(unseen)
            component.extend(unseen)
        if len(component) > 1:
            cycles.append(sorted(component))
    return sorted(cycles)


def _fk_table_key(table: _TableKey) -> _TableKey:
    schema, name = table
    return schema.casefold(), name.casefold()


def _related_tables(
    tables: Iterable[_TableKey],
    related: dict[_TableKey, set[_TableKey]],
) -> set[_TableKey]:
    found = set(tables)
    pending = list(found)
    while pending:
        neighbors = related.get(pending.pop(), set()) - found
        found.update(neighbors)
        pending.extend(neighbors)
    return found


def _record_import_table_error(
    metadata: TableMetadata,
    csvs: Sequence[tuple[Path, TableMetadata]],
    summary: DatabaseCsvSummary,
    logger: Logger,
    exc: Exception,
) -> None:
    if csvs:
        for csv_path, _ in csvs:
            _record_error(summary, logger, csv_path, exc, table=csv_path.stem)
    else:
        qualified_name = f"{metadata.schema}.{metadata.name}"
        _record_error(summary, logger, qualified_name, exc, table=qualified_name)


def _record_import_cycles(
    cycles: Sequence[Sequence[_TableKey]],
    tables: dict[_TableKey, TableMetadata],
    imports: _ImportTables,
    summary: DatabaseCsvSummary,
    logger: Logger,
) -> None:
    for cycle in cycles:
        names = ", ".join(f"{tables[key].schema}.{tables[key].name}" for key in cycle)
        error = ValueError(f"Chu trình khóa ngoại giữa các table: {names}")
        for key in cycle:
            _record_import_table_error(tables[key], imports.get(key, ()), summary, logger, error)


def _clear_import_tables(
    connection,
    adapter: DatabaseAdapter,
    imports: _ImportTables,
    edges: Sequence[ForeignKeyEdge],
    csv_stems: set[str],
    summary: DatabaseCsvSummary,
    logger: Logger,
    cancel: CancelChecker | None,
) -> set[_TableKey]:
    tables = {key: csvs[0][1] for key, csvs in imports.items()}
    parents: dict[_TableKey, set[_TableKey]] = {}
    children: dict[_TableKey, set[_TableKey]] = {}
    for edge in edges:
        parent, child = _fk_table_key(edge.parent), _fk_table_key(edge.child)
        children.setdefault(parent, set()).add(child)
        parents.setdefault(child, set()).add(parent)
        tables.setdefault(child, TableMetadata(edge.child_schema, edge.child_table, []))

    closure = _related_tables(imports, children)
    order, cycles = order_tables_by_dependency(closure, edges)
    if cycles:
        _record_import_cycles(cycles, tables, imports, summary, logger)
        cyclic = {key for cycle in cycles for key in cycle}
        blocked = _related_tables(cyclic, parents) & closure
        # A parent cannot be cleared while a cyclic child and its rows remain.
        for key in sorted((blocked - cyclic) & imports.keys()):
            cyclic_children = sorted(_related_tables([key], children) & cyclic)
            names = ", ".join(f"{tables[child].schema}.{tables[child].name}" for child in cyclic_children)
            exc = ValueError(f"Không thể xóa dữ liệu vì table phụ thuộc có chu trình khóa ngoại: {names}")
            _record_import_table_error(tables[key], imports[key], summary, logger, exc)
        clearable = _related_tables(imports.keys() - blocked, children)
        order = [key for key in order if key in clearable]
    if not order:
        return set()

    clear_steps = [
        (key, "TRUNCATE TABLE" if key not in children and adapter.transactional_truncate else "DELETE FROM")
        for key in reversed(order)
    ]
    labels = {key: adapter.qualified_table(tables[key]) for key, _ in clear_steps}
    logger("Thứ tự xóa dữ liệu: " + " → ".join(f"{action} {labels[key]}" for key, action in clear_steps))
    csv_schemas = {schema for schema, _ in imports}
    for key, _ in clear_steps:
        if key not in imports:
            schema, name = key
            location = "ngoài tập CSV nhập" if schema in csv_schemas and name in csv_stems else "ngoài folder CSV"
            logger(f"Xóa thêm table {location}: {labels[key]}")

    cursor = None
    target = "bắt đầu pha xóa dữ liệu"
    try:
        _check_cancel(cancel)
        cursor = connection.cursor()
        adapter.validate_import_clear(cursor, [tables[key] for key, _ in clear_steps])
        for key, action in clear_steps:
            _check_cancel(cancel)
            target = f"{action} {labels[key]}"
            if action == "TRUNCATE TABLE":
                adapter.truncate_table(cursor, tables[key])
            else:
                adapter.execute(cursor, target)
        _check_cancel(cancel)
        target = "commit pha xóa dữ liệu"
        connection.commit()
    except Exception as exc:
        try:
            connection.rollback()
        except Exception as rollback_error:
            logger(f"Không thể rollback pha xóa dữ liệu: {rollback_error}")
        if isinstance(exc, OperationCancelledError):
            raise
        error = RuntimeError(f"Pha xóa dữ liệu thất bại tại {target}: {exc}")
        for key, _ in clear_steps:
            _record_import_table_error(tables[key], imports.get(key, ()), summary, logger, error)
        return set()
    finally:
        if cursor is not None:
            _close_cursor(cursor)
    return set(order)


def import_csv_folder(
    root_path: str | Path,
    settings: DatabaseConnectionSettings,
    keep_identity: bool = False,
    log: Logger | None = None,
    existing_row_mode: str = IMPORT_MODE_APPEND,
    cancel: CancelChecker | None = None,
    table_names: Iterable[str] | str | None = None,
) -> DatabaseCsvSummary:
    root = _validate_folder(root_path, must_exist=True)
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    logger = log or (lambda message: None)
    existing_row_mode = _validate_import_mode(existing_row_mode)
    requested_tables = _parse_table_names(table_names)
    requested_table_keys = {name.casefold() for name in requested_tables}
    summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=root)

    connection = adapter.connect(settings)
    try:
        csv_paths = _iter_direct_csv_files(root)
        csv_stems = {csv_path.stem.casefold() for csv_path in csv_paths}
        imports: _ImportTables = {}
        for csv_path in csv_paths:
            if requested_table_keys and csv_path.stem.casefold() not in requested_table_keys:
                continue
            _check_cancel(cancel)
            try:
                prepared = _read_import_csv(connection, adapter, settings, root, csv_path, keep_identity, summary, logger)
                if prepared is not None:
                    metadata = prepared[0]
                    key = _fk_table_key((metadata.schema, metadata.name))
                    imports.setdefault(key, []).append((csv_path, metadata))
                del prepared  # Keep at most one CSV's rows in memory during preparation.
            except OperationCancelledError:
                raise
            except Exception as exc:
                connection.rollback()
                _record_error(summary, logger, csv_path, exc, table=csv_path.stem)

        truncate_mode = existing_row_mode == IMPORT_MODE_TRUNCATE_TABLE
        edges = []
        if len(imports) > 1 or (imports and truncate_mode):
            _check_cancel(cancel)
            try:
                edges = adapter.list_foreign_keys(connection, settings)
            except OperationCancelledError:
                raise
            except Exception as exc:
                connection.rollback()
                logger(f"Không đọc được khóa ngoại: {exc}")

        import_order = list(imports)
        cleared = set()
        if edges:
            if truncate_mode:
                cleared = _clear_import_tables(connection, adapter, imports, edges, csv_stems, summary, logger, cancel)
                import_order, _ = order_tables_by_dependency(imports.keys() & cleared, edges)
            else:
                import_order, cycles = order_tables_by_dependency(imports, edges)
                if cycles:
                    tables = {key: csvs[0][1] for key, csvs in imports.items()}
                    for cycle in cycles:
                        names = ", ".join(f"{tables[key].schema}.{tables[key].name}" for key in cycle)
                        logger(f"Cảnh báo: chu trình khóa ngoại giữa {names}; import theo thứ tự tên")
                    import_order.extend(sorted(key for cycle in cycles for key in cycle))
        if import_order:
            logger("Thứ tự import: " + " → ".join(
                f"{metadata.schema}.{metadata.name}" for key in import_order for _, metadata in imports[key]
            ))

        for key in import_order:
            for csv_path, metadata in imports[key]:
                _import_one_csv(
                    connection, adapter, settings, root, csv_path, keep_identity, summary, logger,
                    existing_row_mode, cancel, already_cleared=key in cleared, metadata=metadata,
                )
        summary.skipped_items.extend(
            DatabaseCsvIssue(name, "Không tìm thấy CSV phù hợp với table đã chọn")
            for name in requested_tables if name.casefold() not in csv_stems
        )
        if requested_tables and summary.csv_count == 0:
            message = "Không tìm thấy CSV phù hợp với table đã chọn: " + ", ".join(requested_tables)
            summary.skipped.append(message)
            logger(message)
    finally:
        connection.close()

    _log_summary(summary, logger, include_items=True)
    return summary


def export_csv_folder(
    output_path: str | Path,
    settings: DatabaseConnectionSettings,
    table_names: Iterable[str] | str | None = None,
    log: Logger | None = None,
    cancel: CancelChecker | None = None,
) -> DatabaseCsvSummary:
    output = _validate_folder(output_path, must_exist=False)
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    logger = log or (lambda message: None)
    summary = DatabaseCsvSummary(action_name="Xuất CSDL ra CSV", root_path=output)
    requested_tables = _parse_table_names(table_names)

    connection = adapter.connect(settings)
    try:
        tables = requested_tables or adapter.list_tables(connection, settings)
        _check_cancel(cancel)
        if not tables:
            message = "Không tìm thấy table để xuất."
            _record_skip(summary, logger, "", message, message)

        for raw_table_name in tables:
            _check_cancel(cancel)
            _export_one_table(connection, adapter, settings, output, raw_table_name, summary, logger, cancel)
    finally:
        connection.close()

    _log_summary(summary, logger, include_items=True)
    return summary


def sync_database_tables(
    source_settings: DatabaseConnectionSettings,
    target_settings: DatabaseConnectionSettings,
    table_names: Iterable[str] | str | None = None,
    record_limit: int | str | None = None,
    keep_identity: bool = True,
    truncate_before_sync: bool = False,
    log: Logger | None = None,
    sync_mode: str | None = None,
    batch_size: int | str | None = DEFAULT_SYNC_BATCH_SIZE,
    delete_target_only: bool = True,
    where_clause: str = "",
    duplicate_mode: str = SYNC_DUPLICATE_ERROR,
    backup_root: str | Path | None = None,
    cancel: CancelChecker | None = None,
    activity: Callable[[str], None] | None = None,
) -> DatabaseSyncSummary:
    source_settings = validate_connection_settings(source_settings)
    target_settings = validate_connection_settings(target_settings)
    source_adapter = get_adapter(source_settings.normalized_type)
    target_adapter = get_adapter(target_settings.normalized_type)
    requested_tables = _parse_table_names(table_names)
    limit = _parse_record_limit(record_limit)
    mode = _validate_sync_mode(sync_mode, truncate_before_sync)
    parsed_batch_size = _parse_sync_batch_size(batch_size)
    normalized_where_clause = _normalize_sync_where_clause(where_clause)
    parsed_duplicate_mode = _validate_sync_duplicate_mode(duplicate_mode)
    if mode == SYNC_MODE_INCREMENTAL and limit is not None:
        raise ValueError(
            "Chế độ đồng bộ chênh lệch không dùng giới hạn record vì có thể bỏ sót record cần xóa ở đích."
        )
    if mode == SYNC_MODE_CONDITION and not normalized_where_clause:
        raise ValueError("Vui lòng nhập điều kiện WHERE khi đồng bộ theo điều kiện.")
    if mode != SYNC_MODE_CONDITION and normalized_where_clause:
        raise ValueError("Điều kiện WHERE chỉ được dùng với chế độ đồng bộ theo điều kiện.")
    if mode == SYNC_MODE_CONDITION and limit is not None:
        raise ValueError("Chế độ đồng bộ theo điều kiện không dùng giới hạn record.")
    logger = log or (lambda message: None)
    summary = DatabaseSyncSummary()
    # Limit memory and single-call latency even for an old cached 100000-row setting.
    if parsed_batch_size > 500:
        logger(f"Chia batch {parsed_batch_size} thành các lượt tối đa 500 record để giảm thời gian chờ và bộ nhớ.")
        parsed_batch_size = 500

    def connect(adapter, settings, label):
        _check_cancel(cancel)
        if activity:
            activity(f"Kết nối {label}")
        connection = adapter.connect(settings)
        if activity:
            from .database_sync_worker import ObservedConnection
            fast_batch = settings.normalized_type == DATABASE_SQLSERVER and settings.driver in {
                "ODBC Driver 17 for SQL Server", "ODBC Driver 18 for SQL Server",
            }
            connection = ObservedConnection(connection, activity, label, fast_batch=fast_batch)
        return connection

    source_connection = None
    target_connection = None
    target_read_connection = None
    try:
        source_connection = connect(source_adapter, source_settings, "nguồn")
        target_connection = connect(target_adapter, target_settings, "đích ghi")
        target_read_connection = (
            connect(target_adapter, target_settings, "đích đọc")
            if mode == SYNC_MODE_INCREMENTAL
            else target_connection
        )
        tables = requested_tables or source_adapter.list_tables(source_connection, source_settings)
        _check_cancel(cancel)
        if not tables:
            message = "Không tìm thấy table để đồng bộ."
            summary.skipped.append(message)
            logger(message)
            return summary

        total_tables = len(tables)
        if mode == SYNC_MODE_CONDITION and parsed_duplicate_mode != SYNC_DUPLICATE_ERROR:
            summary.backup_path = _prepare_sync_backup_dir(tables, backup_root)
            logger(f"Backup record đích trước khi xử lý trùng key: {summary.backup_path}")
        for table_index, raw_table_name in enumerate(tables, start=1):
            _check_cancel(cancel)
            _sync_one_table(
                source_connection,
                target_connection,
                source_adapter,
                target_adapter,
                source_settings,
                target_settings,
                raw_table_name,
                limit,
                keep_identity,
                truncate_before_sync,
                summary,
                logger,
                sync_mode=mode,
                batch_size=parsed_batch_size,
                delete_target_only=delete_target_only,
                where_clause=normalized_where_clause,
                duplicate_mode=parsed_duplicate_mode,
                backup_dir=summary.backup_path,
                target_read_connection=target_read_connection,
                table_index=table_index,
                total_tables=total_tables,
                cancel=cancel,
            )
    finally:
        if target_read_connection is not None and target_read_connection is not target_connection:
            target_read_connection.close()
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()

    _log_sync_summary(summary, logger)
    return summary


def validate_database_listing_settings(settings: DatabaseConnectionSettings) -> DatabaseConnectionSettings:
    database_type = normalize_database_type(settings.database_type)
    host = settings.host.strip()
    database = settings.database.strip()
    schema = settings.schema.strip()
    username = settings.username.strip()

    if database_type in {DATABASE_SQLSERVER, DATABASE_MYSQL, DATABASE_POSTGRESQL} and not host:
        raise ValueError("Vui lòng nhập máy chủ CSDL.")
    if database_type == DATABASE_SQLSERVER:
        if not settings.driver.strip():
            raise ValueError("Vui lòng nhập ODBC driver cho SQL Server.")
        if not settings.trusted_connection and not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
        database = database or "master"
        schema = schema or "dbo"
    elif database_type == DATABASE_POSTGRESQL:
        if not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
        database = database or "postgres"
        schema = schema or "public"
    elif database_type == DATABASE_MYSQL:
        if not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
        schema = schema or database
    elif database_type == DATABASE_ORACLE:
        if not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
        if not database:
            raise ValueError("Oracle cần tên service/DSN để kết nối.")
        schema = schema or username.upper()

    return DatabaseConnectionSettings(
        database_type=database_type,
        host=host,
        database=database,
        schema=schema,
        port=settings.port.strip() or default_port(database_type),
        username=username,
        password=settings.password,
        trusted_connection=settings.trusted_connection,
        driver=settings.driver.strip(),
        trust_server_certificate=settings.trust_server_certificate,
        encrypt=settings.encrypt,
    )


def validate_connection_settings(settings: DatabaseConnectionSettings) -> DatabaseConnectionSettings:
    database_type = normalize_database_type(settings.database_type)
    host = settings.host.strip()
    database = settings.database.strip()
    schema = settings.schema.strip()
    username = settings.username.strip()

    if database_type in {DATABASE_SQLSERVER, DATABASE_MYSQL, DATABASE_POSTGRESQL} and not host:
        raise ValueError("Vui lòng nhập máy chủ CSDL.")
    if not database:
        raise ValueError("Vui lòng nhập CSDL/tên dịch vụ.")
    if database_type == DATABASE_SQLSERVER:
        if not settings.driver.strip():
            raise ValueError("Vui lòng nhập ODBC driver cho SQL Server.")
        if not settings.trusted_connection and not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
        schema = schema or "dbo"
    elif database_type == DATABASE_POSTGRESQL:
        schema = schema or "public"
        if not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
    elif database_type == DATABASE_MYSQL:
        schema = schema or database
        if not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
    elif database_type == DATABASE_ORACLE:
        if not username:
            raise ValueError("Vui lòng nhập người dùng CSDL.")
        schema = schema or username.upper()

    return DatabaseConnectionSettings(
        database_type=database_type,
        host=host,
        database=database,
        schema=schema,
        port=settings.port.strip() or default_port(database_type),
        username=username,
        password=settings.password,
        trusted_connection=settings.trusted_connection,
        driver=settings.driver.strip(),
        trust_server_certificate=settings.trust_server_certificate,
        encrypt=settings.encrypt,
    )


def get_adapter(database_type: str) -> DatabaseAdapter:
    normalized = normalize_database_type(database_type)
    if normalized == DATABASE_SQLSERVER:
        return SqlServerAdapter()
    if normalized == DATABASE_MYSQL:
        return MySqlAdapter()
    if normalized == DATABASE_POSTGRESQL:
        return PostgreSqlAdapter()
    if normalized == DATABASE_ORACLE:
        return OracleAdapter()
    raise ValueError(f"Loại database chưa được hỗ trợ: {database_type}")


def _normalize_one_csv(
    connection,
    adapter: DatabaseAdapter,
    settings: DatabaseConnectionSettings,
    root: Path,
    csv_path: Path,
    summary: DatabaseCsvSummary,
    logger: Logger,
    cancel: CancelChecker | None = None,
) -> None:
    relative_csv_path = _relative_to(csv_path, root)
    try:
        _check_cancel(cancel)
        table = read_dbeaver_csv(csv_path)
        if not table.headers:
            message = f"{relative_csv_path} -> bỏ qua CSV rỗng"
            summary.skipped.append(message)
            logger(message)
            return

        metadata = adapter.get_table(connection, settings, csv_path.stem)
        mapping = _build_column_mapping(table.headers, metadata.columns)
        ordered_headers = [column.name for column in mapping.columns]
        ordered_rows = [
            [
                _format_csv_value(row[mapping.csv_index_by_db_name[column.name]], column)
                for column in mapping.columns
            ]
            for row in table.rows
        ]
        _check_cancel(cancel)
        write_dbeaver_csv(csv_path, ordered_headers, ordered_rows)
        summary.csv_results.append(
            CsvDbResult(csv_path=csv_path, table_name=metadata.name, row_count=len(table.rows))
        )
        logger(f"{relative_csv_path} -> đã chuẩn hóa theo {metadata.schema}.{metadata.name} ({len(table.rows)} dòng)")
    except TableNotFoundError:
        message = f"{relative_csv_path} -> bỏ qua vì không tìm thấy table: {settings.schema}.{csv_path.stem}"
        summary.skipped.append(message)
        logger(message)
    except OperationCancelledError:
        raise
    except Exception as exc:
        _record_error(summary, logger, csv_path, exc)


def _read_import_csv(
    connection,
    adapter: DatabaseAdapter,
    settings: DatabaseConnectionSettings,
    root: Path,
    csv_path: Path,
    keep_identity: bool,
    summary: DatabaseCsvSummary,
    logger: Logger,
    metadata: TableMetadata | None = None,
) -> tuple[TableMetadata, DbeaverCsv, CsvColumnMapping] | None:
    relative_csv_path = _relative_to(csv_path, root)
    table = read_dbeaver_csv(csv_path)
    if not table.headers:
        reason = "bỏ qua CSV rỗng"
    else:
        try:
            if metadata is None:
                metadata = adapter.get_table(connection, settings, csv_path.stem)
        except TableNotFoundError:
            reason = f"bỏ qua vì không tìm thấy table: {settings.schema}.{csv_path.stem}"
        else:
            mapping = _build_import_mapping(table, metadata.columns, adapter, keep_identity)
            if mapping.columns:
                return metadata, table, mapping
            reason = "bỏ qua vì không có column nào có thể nhập"
    _record_skip(summary, logger, csv_path.stem, reason, f"{relative_csv_path} -> {reason}")
    return None


def _import_one_csv(
    connection,
    adapter: DatabaseAdapter,
    settings: DatabaseConnectionSettings,
    root: Path,
    csv_path: Path,
    keep_identity: bool,
    summary: DatabaseCsvSummary,
    logger: Logger,
    existing_row_mode: str = IMPORT_MODE_APPEND,
    cancel: CancelChecker | None = None,
    *,
    already_cleared: bool = False,
    metadata: TableMetadata | None = None,
) -> None:
    relative_csv_path = _relative_to(csv_path, root)
    try:
        _check_cancel(cancel)
        prepared = _read_import_csv(connection, adapter, settings, root, csv_path, keep_identity, summary, logger, metadata)
        if prepared is None:
            return
        metadata, table, mapping = prepared

        insert_rows = [
            [row[mapping.csv_index_by_db_name[column.name]] for column in mapping.columns]
            for row in table.rows
        ]
        _check_cancel(cancel)
        cursor = connection.cursor()
        insert_sql = adapter.insert_sql(metadata, mapping.columns, keep_identity)
        try:
            if not already_cleared or existing_row_mode != IMPORT_MODE_TRUNCATE_TABLE:
                _prepare_table_for_import(
                    cursor,
                    adapter,
                    metadata,
                    table,
                    mapping,
                    existing_row_mode,
                    relative_csv_path,
                    logger,
                    cancel,
                )
            adapter.before_import(cursor, metadata, mapping.columns, keep_identity)
            import_error: Exception | None = None
            try:
                if insert_rows:
                    _check_cancel(cancel)
                    adapter.executemany(cursor, insert_sql, insert_rows)
                    _check_cancel(cancel)
            except Exception as exc:
                import_error = exc
            try:
                adapter.after_import(cursor, metadata, mapping.columns, keep_identity)
            except Exception as cleanup_exc:
                if import_error is None:
                    raise
                logger(f"{relative_csv_path} -> lỗi khi dọn trạng thái identity: {cleanup_exc}")
            if import_error is not None:
                raise import_error
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        if mapping.skipped_columns:
            logger(f"{relative_csv_path} -> bỏ qua column không nhập: {', '.join(mapping.skipped_columns)}")
        summary.csv_results.append(
            CsvDbResult(
                csv_path=csv_path,
                table_name=metadata.name,
                row_count=len(insert_rows),
                skipped_columns=mapping.skipped_columns,
            )
        )
        summary.succeeded.append(DatabaseCsvSuccess(csv_path.stem, len(insert_rows)))
        logger(f"{relative_csv_path} -> đã nhập vào {metadata.schema}.{metadata.name} ({len(insert_rows)} dòng)")
    except TableNotFoundError:
        reason = f"bỏ qua vì không tìm thấy table: {settings.schema}.{csv_path.stem}"
        _record_skip(summary, logger, csv_path.stem, reason, f"{relative_csv_path} -> {reason}")
    except OperationCancelledError:
        raise
    except Exception as exc:
        _record_error(summary, logger, csv_path, exc, table=csv_path.stem)


def _prepare_table_for_import(
    cursor,
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    table: DbeaverCsv,
    mapping: CsvColumnMapping,
    existing_row_mode: str,
    relative_csv_path: Path,
    logger: Logger,
    cancel: CancelChecker | None = None,
) -> None:
    _check_cancel(cancel)
    mode = _validate_import_mode(existing_row_mode)
    if mode == IMPORT_MODE_APPEND:
        return
    if mode == IMPORT_MODE_TRUNCATE_TABLE:
        _check_cancel(cancel)
        adapter.truncate_table(cursor, metadata)
        logger(f"{relative_csv_path} -> đã truncate toàn bộ {metadata.schema}.{metadata.name} trước khi nhập")
        return

    primary_key_columns = [column for column in metadata.columns if column.is_primary_key]
    if not primary_key_columns:
        raise ValueError(
            f"Table {metadata.schema}.{metadata.name} không có primary key; "
            "không thể xác định record trùng để xóa."
        )

    mapped_column_names = {column.name for column in mapping.columns}
    missing_key_headers = [
        column.name for column in primary_key_columns if column.name not in mapping.csv_index_by_db_name
    ]
    if missing_key_headers:
        raise ValueError(
            "CSV thiếu column primary key cần để xóa record trùng: " + ", ".join(missing_key_headers)
        )
    skipped_key_columns = [column.name for column in primary_key_columns if column.name not in mapped_column_names]
    if skipped_key_columns:
        raise ValueError(
            "Primary key không được đưa vào dữ liệu import: "
            + ", ".join(skipped_key_columns)
            + ". Nếu đây là identity, hãy bật tùy chọn giữ identity."
        )

    key_rows: list[tuple[str, ...]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for row_number, row in enumerate(table.rows, start=1):
        if row_number == 1 or row_number % 1000 == 0:
            _check_cancel(cancel)
        key = tuple(row[mapping.csv_index_by_db_name[column.name]] for column in primary_key_columns)
        if any(value is None for value in key):
            key_names = ", ".join(column.name for column in primary_key_columns)
            raise ValueError(f"Primary key là NULL tại record {row_number}: {key_names}")
        typed_key = tuple(str(value) for value in key)
        if typed_key in seen_keys:
            raise ValueError(f"CSV có primary key trùng tại record {row_number}: {typed_key}")
        seen_keys.add(typed_key)
        key_rows.append(typed_key)

    if not key_rows:
        return
    _check_cancel(cancel)
    delete_sql = _build_delete_by_primary_key_sql(adapter, metadata, primary_key_columns)
    adapter.executemany(cursor, delete_sql, key_rows)
    _check_cancel(cancel)
    logger(
        f"{relative_csv_path} -> đã xử lý xóa record trùng theo {len(primary_key_columns)} "
        f"column primary key ({len(key_rows)} key từ CSV) trước khi nhập"
    )


def _build_delete_by_primary_key_sql(
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    primary_key_columns: list[DatabaseColumn] | None = None,
) -> str:
    columns = primary_key_columns or [column for column in metadata.columns if column.is_primary_key]
    if not columns:
        raise ValueError(f"Table {metadata.schema}.{metadata.name} không có primary key.")
    conditions = " AND ".join(
        f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(index)}"
        for index, column in enumerate(columns)
    )
    return f"DELETE FROM {adapter.qualified_table(metadata)} WHERE {conditions}"


def _build_select_by_primary_key_sql(
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    columns: list[DatabaseColumn],
    primary_key_columns: list[DatabaseColumn],
) -> str:
    column_sql = ", ".join(adapter.quote_identifier(column.name) for column in columns)
    conditions = " AND ".join(
        f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(index)}"
        for index, column in enumerate(primary_key_columns)
    )
    return f"SELECT {column_sql} FROM {adapter.qualified_table(metadata)} WHERE {conditions}"


def _validate_import_mode(value: str) -> str:
    normalized = str(value or IMPORT_MODE_APPEND).strip().lower()
    if normalized not in IMPORT_MODES:
        raise ValueError(f"Chế độ xử lý dữ liệu trước import không hợp lệ: {value}")
    return normalized


def _export_one_table(
    connection,
    adapter: DatabaseAdapter,
    settings: DatabaseConnectionSettings,
    output: Path,
    raw_table_name: str,
    summary: DatabaseCsvSummary,
    logger: Logger,
    cancel: CancelChecker | None = None,
) -> None:
    table_name = raw_table_name
    try:
        schema, table_name = _split_table_name(raw_table_name)
        metadata = adapter.get_table(connection, settings, table_name, schema=schema)
        table_name = metadata.name
        columns = metadata.columns
        if not columns:
            reason = "bỏ qua vì không có column xuất"
            _record_skip(summary, logger, table_name, reason, f"{raw_table_name} -> {reason}")
            return

        cursor = connection.cursor()
        select_sql = _build_export_select_sql(adapter, metadata, columns)
        _check_cancel(cancel)
        adapter.execute(cursor, select_sql)
        headers = [column.name for column in columns]
        quote_columns = [column.should_quote_export for column in columns]
        output_file = output / _export_file_name(metadata, schema is not None)
        row_count = write_typed_dbeaver_csv_rows(
            output_file,
            headers,
            _iter_export_rows(cursor, columns, cancel),
            quote_columns,
        )
        summary.csv_results.append(CsvDbResult(csv_path=output_file, table_name=metadata.name, row_count=row_count))
        summary.succeeded.append(DatabaseCsvSuccess(table_name, row_count))
        logger(f"{metadata.schema}.{metadata.name} -> đã xuất {row_count} dòng: {output_file}")
    except OperationCancelledError:
        raise
    except Exception as exc:
        _record_error(summary, logger, output / f"{raw_table_name}.csv", exc, table=table_name)


def _iter_export_rows(cursor, columns: list[DatabaseColumn], cancel: CancelChecker | None = None):
    while True:
        _check_cancel(cancel)
        rows = cursor.fetchmany(5000)
        if not rows:
            return
        for row in rows:
            yield [_format_db_value(row[index], column) for index, column in enumerate(columns)]


def _sync_one_table(
    source_connection,
    target_connection,
    source_adapter: DatabaseAdapter,
    target_adapter: DatabaseAdapter,
    source_settings: DatabaseConnectionSettings,
    target_settings: DatabaseConnectionSettings,
    raw_table_name: str,
    record_limit: int | None,
    keep_identity: bool,
    truncate_before_sync: bool,
    summary: DatabaseSyncSummary,
    logger: Logger,
    sync_mode: str | None = None,
    batch_size: int = DEFAULT_SYNC_BATCH_SIZE,
    delete_target_only: bool = True,
    where_clause: str = "",
    duplicate_mode: str = SYNC_DUPLICATE_ERROR,
    backup_dir: Path | None = None,
    target_read_connection=None,
    table_index: int = 1,
    total_tables: int = 1,
    cancel: CancelChecker | None = None,
) -> None:
    schema, table_name = _split_table_name(raw_table_name)
    try:
        _check_cancel(cancel)
        mode = _validate_sync_mode(sync_mode, truncate_before_sync)
        source_metadata = source_adapter.get_table(source_connection, source_settings, table_name, schema=schema)
        target_metadata = target_adapter.get_table(target_connection, target_settings, table_name, schema=schema)
        source_columns, target_columns, skipped_columns = _build_sync_columns(
            source_metadata,
            target_metadata,
            target_adapter,
            keep_identity,
        )
        if not target_columns:
            message = f"{raw_table_name} -> bỏ qua vì không có column nào có thể đồng bộ"
            summary.skipped.append(message)
            logger(message)
            return

        source_total_rows = _count_table_rows(
            source_adapter,
            source_connection,
            source_metadata,
            where_clause if mode == SYNC_MODE_CONDITION else "",
        )
        if record_limit is not None and source_total_rows is not None:
            source_total_rows = min(source_total_rows, record_limit)

        if mode == SYNC_MODE_CONDITION:
            result = _sync_one_table_condition(
                source_connection,
                target_connection,
                source_adapter,
                target_adapter,
                source_metadata,
                target_metadata,
                source_columns,
                target_columns,
                skipped_columns,
                keep_identity,
                batch_size,
                where_clause,
                duplicate_mode,
                backup_dir,
                logger=logger,
                source_total_rows=source_total_rows,
                table_index=table_index,
                total_tables=total_tables,
                cancel=cancel,
            )
            summary.table_results.append(result)
            if skipped_columns:
                logger(f"{raw_table_name} -> bỏ qua column không đồng bộ: {', '.join(skipped_columns)}")
            logger(
                f"{raw_table_name} -> đồng bộ theo điều kiện: nguồn {result.source_row_count}, "
                f"insert {result.inserted_count}, update {result.updated_count}, "
                f"delete {result.deleted_count}, backup {result.backup_row_count}"
            )
            return

        if mode == SYNC_MODE_INCREMENTAL:
            result = _sync_one_table_incremental(
                source_connection,
                target_read_connection or target_connection,
                target_connection,
                source_adapter,
                target_adapter,
                source_metadata,
                target_metadata,
                source_columns,
                target_columns,
                skipped_columns,
                keep_identity,
                batch_size,
                delete_target_only,
                logger=logger,
                source_total_rows=source_total_rows,
                table_index=table_index,
                total_tables=total_tables,
                cancel=cancel,
            )
            summary.table_results.append(result)
            if skipped_columns:
                logger(f"{raw_table_name} -> bỏ qua column không đồng bộ: {', '.join(skipped_columns)}")
            logger(
                f"{raw_table_name} -> đã quét nguồn {result.source_row_count} / đích {result.target_row_count}; "
                f"insert {result.inserted_count}, update {result.updated_count}, "
                f"delete {result.deleted_count}, không đổi {result.unchanged_count}"
            )
            if result.retained_target_only_count:
                logger(
                    f"{raw_table_name} -> giữ lại {result.retained_target_only_count} record chỉ có ở CSDL đích"
                )
            return

        source_cursor = source_adapter.stream_cursor(source_connection)
        source_sql = _build_sync_select_sql(source_adapter, source_metadata, source_columns)
        _check_cancel(cancel)
        source_adapter.execute(source_cursor, source_sql)
        remaining = record_limit
        first_fetch_size = batch_size if remaining is None else min(batch_size, remaining)
        rows = source_cursor.fetchmany(first_fetch_size)
        insert_rows = [tuple(row[index] for index, _column in enumerate(source_columns)) for row in rows]
        inserted_count = len(insert_rows)
        started_at = time_module.monotonic()
        _log_sync_progress(
            logger,
            table_name=raw_table_name,
            current=0,
            total=source_total_rows,
            table_index=table_index,
            total_tables=total_tables,
            mode=mode,
            started_at=started_at,
        )

        target_cursor = target_connection.cursor()
        insert_sql = target_adapter.insert_sql(target_metadata, target_columns, keep_identity)
        try:
            if mode == SYNC_MODE_TRUNCATE_TABLE:
                _check_cancel(cancel)
                target_adapter.truncate_table(target_cursor, target_metadata)
                logger(f"{raw_table_name} -> đã truncate dữ liệu đích trước khi đồng bộ")
            target_adapter.before_import(target_cursor, target_metadata, target_columns, keep_identity)
            sync_error: Exception | None = None
            try:
                if insert_rows:
                    _check_cancel(cancel)
                    target_adapter.executemany(target_cursor, insert_sql, insert_rows)
                    _check_cancel(cancel)
                    if remaining is not None:
                        remaining -= len(insert_rows)
                    if inserted_count >= 100:
                        _log_sync_progress(
                            logger,
                            table_name=raw_table_name,
                            current=inserted_count,
                            total=source_total_rows,
                            table_index=table_index,
                            total_tables=total_tables,
                            mode=mode,
                            started_at=started_at,
                            inserted=inserted_count,
                        )
                while rows and (remaining is None or remaining > 0):
                    _check_cancel(cancel)
                    fetch_size = batch_size if remaining is None else min(batch_size, remaining)
                    rows = source_cursor.fetchmany(fetch_size)
                    if not rows:
                        break
                    insert_rows = [tuple(row[index] for index, _column in enumerate(source_columns)) for row in rows]
                    _check_cancel(cancel)
                    target_adapter.executemany(target_cursor, insert_sql, insert_rows)
                    inserted_count += len(insert_rows)
                    if remaining is not None:
                        remaining -= len(insert_rows)
                    if inserted_count == 100 or inserted_count % max(batch_size, 1000) == 0:
                        _log_sync_progress(
                            logger,
                            table_name=raw_table_name,
                            current=inserted_count,
                            total=source_total_rows,
                            table_index=table_index,
                            total_tables=total_tables,
                            mode=mode,
                            started_at=started_at,
                            inserted=inserted_count,
                        )
            except Exception as exc:
                sync_error = exc
            try:
                target_adapter.after_import(target_cursor, target_metadata, target_columns, keep_identity)
            except Exception as cleanup_exc:
                if sync_error is None:
                    raise
                logger(f"{raw_table_name} -> lỗi khi dọn trạng thái identity: {cleanup_exc}")
            if sync_error is not None:
                raise sync_error
            _check_cancel(cancel)
            target_connection.commit()
        except Exception:
            target_connection.rollback()
            raise
        finally:
            _close_cursor(source_cursor)
            _close_cursor(target_cursor)

        if skipped_columns:
            logger(f"{raw_table_name} -> bỏ qua column không insert: {', '.join(skipped_columns)}")
        summary.table_results.append(
            DatabaseSyncResult(
                table_name=target_metadata.name,
                row_count=inserted_count,
                skipped_columns=tuple(skipped_columns),
                source_row_count=inserted_count,
                inserted_count=inserted_count,
            )
        )
        _log_sync_progress(
            logger,
            table_name=raw_table_name,
            current=inserted_count,
            total=source_total_rows,
            table_index=table_index,
            total_tables=total_tables,
            mode=mode,
            started_at=started_at,
            inserted=inserted_count,
            done=True,
        )
        logger(f"{raw_table_name} -> đã đồng bộ {inserted_count} dòng vào {target_metadata.schema}.{target_metadata.name}")
    except OperationCancelledError:
        raise
    except Exception as exc:
        message = f"LỖI {raw_table_name}: {exc}"
        summary.errors.append(message)
        logger(message)


def _sync_one_table_condition(
    source_connection,
    target_connection,
    source_adapter: DatabaseAdapter,
    target_adapter: DatabaseAdapter,
    source_metadata: TableMetadata,
    target_metadata: TableMetadata,
    source_columns: list[DatabaseColumn],
    target_columns: list[DatabaseColumn],
    skipped_columns: tuple[str, ...],
    keep_identity: bool,
    batch_size: int,
    where_clause: str,
    duplicate_mode: str,
    backup_dir: Path | None = None,
    logger: Logger | None = None,
    source_total_rows: int | None = None,
    table_index: int = 1,
    total_tables: int = 1,
    cancel: CancelChecker | None = None,
) -> DatabaseSyncResult:
    _check_cancel(cancel)
    batch_size = _parse_sync_batch_size(batch_size)
    where_clause = _normalize_sync_where_clause(where_clause)
    duplicate_mode = _validate_sync_duplicate_mode(duplicate_mode)
    source_key_columns, target_key_columns, key_indexes = _build_delta_key_columns(
        source_metadata,
        target_metadata,
        source_columns,
        target_columns,
    )
    key_names = {column.name.lower() for column in target_key_columns}
    update_indexes = [
        index
        for index, column in enumerate(target_columns)
        if column.name.lower() not in key_names and not column.is_identity
    ]
    update_columns = [target_columns[index] for index in update_indexes]

    source_cursor = source_adapter.stream_cursor(source_connection)
    target_cursor = target_connection.cursor()
    source_sql = _build_sync_select_sql(
        source_adapter,
        source_metadata,
        source_columns,
        order_columns=source_key_columns,
        where_clause=where_clause,
    )
    insert_sql = target_adapter.insert_sql(target_metadata, target_columns, keep_identity)
    update_sql = _build_sync_update_sql(target_adapter, target_metadata, update_columns, target_key_columns)
    delete_sql = _build_delete_by_primary_key_sql(target_adapter, target_metadata, target_key_columns)
    backup_columns = target_metadata.columns
    backup_writer = _open_sync_backup_writer(backup_dir, target_metadata, backup_columns)
    backup_index_by_name = {column.name.lower(): index for index, column in enumerate(backup_columns)}

    source_row_count = 0
    target_row_count = 0
    inserted_count = 0
    updated_count = 0
    deleted_count = 0
    unchanged_count = 0
    backup_row_count = 0
    identity_active = False
    operation_error: Exception | None = None
    progress_logger = logger or (lambda _message: None)
    started_at = time_module.monotonic()
    next_progress_mark = 100
    progress_step = max(batch_size, 1000)
    _log_sync_progress(
        progress_logger,
        table_name=source_metadata.name,
        current=0,
        total=source_total_rows,
        table_index=table_index,
        total_tables=total_tables,
        mode=SYNC_MODE_CONDITION,
        started_at=started_at,
    )

    def ensure_identity_state() -> None:
        nonlocal identity_active
        if not identity_active:
            target_adapter.before_import(target_cursor, target_metadata, target_columns, keep_identity)
            identity_active = True

    def write_backup_rows(rows: Iterable[Sequence[object]]) -> None:
        nonlocal backup_row_count
        if backup_writer is None:
            return
        formatted_rows = (
            [_format_db_value(row[index], column) for index, column in enumerate(backup_columns)]
            for row in rows
        )
        backup_row_count += backup_writer.write_rows(formatted_rows)
        # The worker may be stopped mid-batch. Persist backups BEFORE mutating DB.
        backup_writer.flush()

    try:
        _check_cancel(cancel)
        source_adapter.execute(source_cursor, source_sql)
        for source_rows in _iter_cursor_batches(source_cursor, batch_size, cancel):
            source_rows = [tuple(row[index] for index, _column in enumerate(source_columns)) for row in source_rows]
            if not source_rows:
                continue
            source_row_count += len(source_rows)
            raw_keys = [tuple(row[index] for index in key_indexes) for row in source_rows]
            existing_by_key: dict[tuple[object, ...], tuple[object, ...]] = {}
            if duplicate_mode != SYNC_DUPLICATE_ERROR:
                existing_backup_by_key = _fetch_target_rows_by_keys(
                    target_adapter,
                    target_connection,
                    target_metadata,
                    backup_columns,
                    target_key_columns,
                    raw_keys,
                    cancel,
                )
                existing_by_key = {
                    key: tuple(row[backup_index_by_name[column.name.lower()]] for column in target_columns)
                    for key, row in existing_backup_by_key.items()
                }
                target_row_count += len(existing_by_key)
                write_backup_rows(existing_backup_by_key.values())

            if duplicate_mode == SYNC_DUPLICATE_DELETE_INSERT:
                existing_raw_keys = [
                    key
                    for key in raw_keys
                    if _sync_key_from_values(key, target_key_columns) in existing_by_key
                ]
                if existing_raw_keys:
                    _check_cancel(cancel)
                    target_adapter.executemany(target_cursor, delete_sql, existing_raw_keys)
                    deleted_count += len(existing_raw_keys)
                _check_cancel(cancel)
                ensure_identity_state()
                target_adapter.executemany(target_cursor, insert_sql, source_rows)
                inserted_count += len(source_rows)
            elif duplicate_mode == SYNC_DUPLICATE_UPSERT:
                insert_rows: list[tuple[object, ...]] = []
                update_rows: list[tuple[object, ...]] = []
                for row, raw_key in zip(source_rows, raw_keys):
                    target_row = existing_by_key.get(_sync_key_from_values(raw_key, target_key_columns))
                    if target_row is None:
                        insert_rows.append(row)
                        continue
                    if update_sql is None:
                        unchanged_count += 1
                        continue
                    source_values = tuple(
                        _canonical_sync_value(row[index], target_columns[index])
                        for index in update_indexes
                    )
                    target_values = tuple(
                        _canonical_sync_value(target_row[index], target_columns[index])
                        for index in update_indexes
                    )
                    if source_values != target_values:
                        update_rows.append(tuple(row[index] for index in update_indexes) + raw_key)
                    else:
                        unchanged_count += 1
                if update_rows and update_sql is not None:
                    _check_cancel(cancel)
                    target_adapter.executemany(target_cursor, update_sql, update_rows)
                    updated_count += len(update_rows)
                if insert_rows:
                    _check_cancel(cancel)
                    ensure_identity_state()
                    target_adapter.executemany(target_cursor, insert_sql, insert_rows)
                    inserted_count += len(insert_rows)
            else:
                _check_cancel(cancel)
                ensure_identity_state()
                target_adapter.executemany(target_cursor, insert_sql, source_rows)
                inserted_count += len(source_rows)

            if source_row_count >= next_progress_mark:
                _log_sync_progress(
                    progress_logger,
                    table_name=source_metadata.name,
                    current=source_row_count,
                    total=source_total_rows,
                    table_index=table_index,
                    total_tables=total_tables,
                    mode=SYNC_MODE_CONDITION,
                    started_at=started_at,
                    inserted=inserted_count,
                    updated=updated_count,
                    deleted=deleted_count,
                    unchanged=unchanged_count,
                )
                next_progress_mark += progress_step
    except Exception as exc:
        operation_error = exc

    cleanup_error: Exception | None = None
    if identity_active:
        try:
            target_adapter.after_import(target_cursor, target_metadata, target_columns, keep_identity)
        except Exception as exc:
            cleanup_error = exc

    try:
        if operation_error is not None:
            raise operation_error
        if cleanup_error is not None:
            raise cleanup_error
        _check_cancel(cancel)
        target_connection.commit()
    except Exception:
        target_connection.rollback()
        raise
    finally:
        if backup_writer is not None:
            backup_writer.close()
        _close_cursor(source_cursor)
        _close_cursor(target_cursor)

    _log_sync_progress(
        progress_logger,
        table_name=source_metadata.name,
        current=source_row_count,
        total=source_total_rows,
        table_index=table_index,
        total_tables=total_tables,
        mode=SYNC_MODE_CONDITION,
        started_at=started_at,
        inserted=inserted_count,
        updated=updated_count,
        deleted=deleted_count,
        unchanged=unchanged_count,
        done=True,
    )

    return DatabaseSyncResult(
        table_name=target_metadata.name,
        row_count=inserted_count + updated_count + deleted_count,
        skipped_columns=tuple(skipped_columns),
        source_row_count=source_row_count,
        target_row_count=target_row_count,
        inserted_count=inserted_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
        unchanged_count=unchanged_count,
        backup_row_count=backup_row_count,
    )


def _sync_one_table_incremental(
    source_connection,
    target_read_connection,
    target_write_connection,
    source_adapter: DatabaseAdapter,
    target_adapter: DatabaseAdapter,
    source_metadata: TableMetadata,
    target_metadata: TableMetadata,
    source_columns: list[DatabaseColumn],
    target_columns: list[DatabaseColumn],
    skipped_columns: tuple[str, ...],
    keep_identity: bool,
    batch_size: int,
    delete_target_only: bool,
    logger: Logger | None = None,
    source_total_rows: int | None = None,
    table_index: int = 1,
    total_tables: int = 1,
    cancel: CancelChecker | None = None,
) -> DatabaseSyncResult:
    _check_cancel(cancel)
    batch_size = _parse_sync_batch_size(batch_size)
    source_key_columns, target_key_columns, key_indexes = _build_delta_key_columns(
        source_metadata,
        target_metadata,
        source_columns,
        target_columns,
    )
    key_names = {column.name.lower() for column in target_key_columns}
    update_indexes = [
        index
        for index, column in enumerate(target_columns)
        if column.name.lower() not in key_names and not column.is_identity
    ]
    update_columns = [target_columns[index] for index in update_indexes]

    source_cursor = source_adapter.stream_cursor(source_connection)
    target_read_cursor = target_adapter.stream_cursor(target_read_connection)
    target_write_cursor = target_write_connection.cursor()
    source_sql = _build_sync_select_sql(
        source_adapter,
        source_metadata,
        source_columns,
        order_columns=source_key_columns,
    )
    target_sql = _build_sync_select_sql(
        target_adapter,
        target_metadata,
        target_columns,
        order_columns=target_key_columns,
    )
    insert_sql = target_adapter.insert_sql(target_metadata, target_columns, keep_identity)
    update_sql = _build_sync_update_sql(target_adapter, target_metadata, update_columns, target_key_columns)
    delete_sql = _build_delete_by_primary_key_sql(target_adapter, target_metadata, target_key_columns)

    source_row_count = 0
    target_row_count = 0
    inserted_count = 0
    updated_count = 0
    deleted_count = 0
    unchanged_count = 0
    retained_target_only_count = 0
    insert_rows: list[tuple[object, ...]] = []
    update_rows: list[tuple[object, ...]] = []
    delete_rows: list[tuple[object, ...]] = []
    identity_active = False
    operation_error: Exception | None = None
    progress_logger = logger or (lambda _message: None)
    started_at = time_module.monotonic()
    next_progress_mark = 100
    progress_step = max(batch_size, 1000)
    _log_sync_progress(
        progress_logger,
        table_name=source_metadata.name,
        current=0,
        total=source_total_rows,
        table_index=table_index,
        total_tables=total_tables,
        mode=SYNC_MODE_INCREMENTAL,
        started_at=started_at,
    )

    def flush_changes() -> None:
        nonlocal identity_active
        _check_cancel(cancel)
        if not insert_rows and not update_rows and not delete_rows:
            return
        if insert_rows and not identity_active:
            target_adapter.before_import(target_write_cursor, target_metadata, target_columns, keep_identity)
            identity_active = True
        if delete_rows:
            target_adapter.executemany(target_write_cursor, delete_sql, delete_rows)
            delete_rows.clear()
        if update_rows and update_sql is not None:
            target_adapter.executemany(target_write_cursor, update_sql, update_rows)
            update_rows.clear()
        if insert_rows:
            target_adapter.executemany(target_write_cursor, insert_sql, insert_rows)
            insert_rows.clear()

    target_snapshot = None
    try:
        _check_cancel(cancel)
        source_adapter.execute(source_cursor, source_sql)
        _check_cancel(cancel)
        target_adapter.execute(target_read_cursor, target_sql)
        source_iterator = _iter_cursor_rows(source_cursor, batch_size)
        if isinstance(target_adapter, SqlServerAdapter) and target_read_connection is not target_write_connection:
            # A streaming SELECT can retain page/table locks and block our own
            # writer on its separate connection. Drain it to disk before DML.
            target_snapshot = tempfile.TemporaryFile()
            progress_logger(f"{target_metadata.name} -> đọc bản đối chiếu đích vào file tạm trước khi ghi để tránh tự chặn khóa.")
            for batch in _iter_cursor_batches(target_read_cursor, batch_size, cancel):
                pickle.dump([tuple(bytes(v) if isinstance(v, memoryview) else v for v in row) for row in batch], target_snapshot)
            _close_cursor(target_read_cursor)
            target_read_cursor = None
            target_read_connection.rollback()
            target_snapshot.seek(0)
            target_iterator = _iter_sync_snapshot(target_snapshot)
        else:
            target_iterator = _iter_cursor_rows(target_read_cursor, batch_size)
        previous_source_key = None
        previous_target_key = None

        def next_source_row():
            nonlocal previous_source_key, source_row_count
            item, previous_source_key = _next_ordered_sync_row(
                source_iterator,
                previous_source_key,
                key_indexes,
                target_key_columns,
                "nguồn",
            )
            if item is not None:
                source_row_count += 1
            return item

        def next_target_row():
            nonlocal previous_target_key, target_row_count
            item, previous_target_key = _next_ordered_sync_row(
                target_iterator,
                previous_target_key,
                key_indexes,
                target_key_columns,
                "đích",
            )
            if item is not None:
                target_row_count += 1
            return item

        source_item = next_source_row()
        target_item = next_target_row()
        while source_item is not None or target_item is not None:
            _check_cancel(cancel)
            if target_item is None or (source_item is not None and source_item[1] < target_item[1]):
                insert_rows.append(source_item[0])
                inserted_count += 1
                source_item = next_source_row()
            elif source_item is None or target_item[1] < source_item[1]:
                if delete_target_only:
                    delete_rows.append(tuple(target_item[0][index] for index in key_indexes))
                    deleted_count += 1
                else:
                    retained_target_only_count += 1
                target_item = next_target_row()
            else:
                source_row, _source_key = source_item
                target_row, _target_key = target_item
                source_values = tuple(
                    _canonical_sync_value(source_row[index], target_columns[index])
                    for index in update_indexes
                )
                target_values = tuple(
                    _canonical_sync_value(target_row[index], target_columns[index])
                    for index in update_indexes
                )
                if source_values != target_values and update_sql is not None:
                    update_rows.append(
                        tuple(source_row[index] for index in update_indexes)
                        + tuple(target_row[index] for index in key_indexes)
                    )
                    updated_count += 1
                else:
                    unchanged_count += 1
                source_item = next_source_row()
                target_item = next_target_row()

            if len(insert_rows) + len(update_rows) + len(delete_rows) >= batch_size:
                flush_changes()
            if source_row_count >= next_progress_mark:
                _log_sync_progress(
                    progress_logger,
                    table_name=source_metadata.name,
                    current=source_row_count,
                    total=source_total_rows,
                    table_index=table_index,
                    total_tables=total_tables,
                    mode=SYNC_MODE_INCREMENTAL,
                    started_at=started_at,
                    inserted=inserted_count,
                    updated=updated_count,
                    deleted=deleted_count,
                    unchanged=unchanged_count,
                )
                next_progress_mark += progress_step

        flush_changes()
    except Exception as exc:
        operation_error = exc

    cleanup_error: Exception | None = None
    if identity_active:
        try:
            target_adapter.after_import(target_write_cursor, target_metadata, target_columns, keep_identity)
        except Exception as exc:
            cleanup_error = exc

    try:
        if operation_error is not None:
            raise operation_error
        if cleanup_error is not None:
            raise cleanup_error
        _check_cancel(cancel)
        target_write_connection.commit()
    except Exception:
        target_write_connection.rollback()
        raise
    finally:
        _close_cursor(source_cursor)
        _close_cursor(target_read_cursor)
        _close_cursor(target_write_cursor)
        if target_snapshot is not None:
            target_snapshot.close()

    _log_sync_progress(
        progress_logger,
        table_name=source_metadata.name,
        current=source_row_count,
        total=source_total_rows,
        table_index=table_index,
        total_tables=total_tables,
        mode=SYNC_MODE_INCREMENTAL,
        started_at=started_at,
        inserted=inserted_count,
        updated=updated_count,
        deleted=deleted_count,
        unchanged=unchanged_count,
        done=True,
    )

    return DatabaseSyncResult(
        table_name=target_metadata.name,
        row_count=inserted_count + updated_count + deleted_count,
        skipped_columns=tuple(skipped_columns),
        source_row_count=source_row_count,
        target_row_count=target_row_count,
        inserted_count=inserted_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
        unchanged_count=unchanged_count,
        retained_target_only_count=retained_target_only_count,
    )


def _count_table_rows(
    adapter: DatabaseAdapter,
    connection,
    metadata: TableMetadata,
    where_clause: str = "",
) -> int | None:
    cursor = connection.cursor()
    try:
        sql = f"SELECT COUNT(*) FROM {adapter.qualified_table(metadata)}"
        normalized_where_clause = _normalize_sync_where_clause(where_clause)
        if normalized_where_clause:
            sql = f"{sql} WHERE ({normalized_where_clause})"
        adapter.execute(cursor, sql)
        row = cursor.fetchone()
        if not row:
            return None
        return int(row[0])
    except Exception:
        return None
    finally:
        _close_cursor(cursor)


def _log_sync_progress(
    logger: Logger,
    *,
    table_name: str,
    current: int,
    total: int | None,
    table_index: int,
    total_tables: int,
    mode: str,
    started_at: float,
    inserted: int = 0,
    updated: int = 0,
    deleted: int = 0,
    unchanged: int = 0,
    done: bool = False,
) -> None:
    elapsed = max(0.001, time_module.monotonic() - started_at)
    speed = current / elapsed if current >= 100 else None
    eta_seconds = None
    if speed and total is not None and total > current:
        eta_seconds = int((total - current) / speed)
    payload = {
        "table": table_name,
        "current": current,
        "total": total,
        "table_index": table_index,
        "total_tables": total_tables,
        "mode": mode,
        "elapsed_seconds": round(elapsed, 3),
        "speed_rows_per_second": round(speed, 2) if speed else None,
        "eta_seconds": eta_seconds,
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
        "unchanged": unchanged,
        "done": done,
    }
    logger(f"{SYNC_PROGRESS_PREFIX}{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}")


def _build_delta_key_columns(
    source_metadata: TableMetadata,
    target_metadata: TableMetadata,
    source_columns: list[DatabaseColumn],
    target_columns: list[DatabaseColumn],
) -> tuple[list[DatabaseColumn], list[DatabaseColumn], list[int]]:
    source_primary_keys = [column for column in source_metadata.columns if column.is_primary_key]
    target_primary_keys = [column for column in target_metadata.columns if column.is_primary_key]
    if not source_primary_keys or not target_primary_keys:
        raise ValueError("Đồng bộ chênh lệch yêu cầu cả table nguồn và table đích có primary key.")

    source_key_names = {column.name.lower() for column in source_primary_keys}
    target_key_names = {column.name.lower() for column in target_primary_keys}
    if source_key_names != target_key_names:
        raise ValueError("Primary key giữa table nguồn và table đích không giống nhau.")

    target_index_by_name = {column.name.lower(): index for index, column in enumerate(target_columns)}
    source_key_columns: list[DatabaseColumn] = []
    mapped_target_key_columns: list[DatabaseColumn] = []
    key_indexes: list[int] = []
    for target_key in target_primary_keys:
        index = target_index_by_name.get(target_key.name.lower())
        if index is None:
            raise ValueError(
                f"Primary key {target_key.name} không được đưa vào dữ liệu đồng bộ. "
                "Nếu đây là identity, hãy bật tùy chọn giữ identity."
            )
        source_key = source_columns[index]
        if not source_key.is_primary_key:
            raise ValueError(f"Column {source_key.name} ở nguồn không phải primary key tương ứng.")
        source_key_columns.append(source_key)
        mapped_target_key_columns.append(target_columns[index])
        key_indexes.append(index)
    return source_key_columns, mapped_target_key_columns, key_indexes


def _build_sync_update_sql(
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    update_columns: list[DatabaseColumn],
    primary_key_columns: list[DatabaseColumn],
) -> str | None:
    if not update_columns:
        return None
    set_sql = ", ".join(
        f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(index)}"
        for index, column in enumerate(update_columns)
    )
    key_offset = len(update_columns)
    where_sql = " AND ".join(
        f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(key_offset + index)}"
        for index, column in enumerate(primary_key_columns)
    )
    return f"UPDATE {adapter.qualified_table(metadata)} SET {set_sql} WHERE {where_sql}"


def _iter_sync_snapshot(snapshot):
    # Only read our own anonymous temporary file; never deserialize user files.
    while True:
        try:
            rows = pickle.load(snapshot)
        except EOFError:
            return
        yield from rows


def _iter_cursor_rows(cursor, batch_size: int):
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        for row in rows:
            yield tuple(row)


def _iter_cursor_batches(cursor, batch_size: int, cancel: CancelChecker | None = None):
    while True:
        _check_cancel(cancel)
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        yield rows


def _fetch_target_rows_by_keys(
    adapter: DatabaseAdapter,
    connection,
    metadata: TableMetadata,
    columns: list[DatabaseColumn],
    primary_key_columns: list[DatabaseColumn],
    raw_keys: Iterable[Sequence[object]],
    cancel: CancelChecker | None = None,
) -> dict[tuple[object, ...], tuple[object, ...]]:
    result: dict[tuple[object, ...], tuple[object, ...]] = {}
    unique_keys: list[tuple[object, ...]] = []
    seen: set[tuple[object, ...]] = set()
    for raw_key in raw_keys:
        key = tuple(raw_key)
        canonical_key = _sync_key_from_values(key, primary_key_columns)
        if canonical_key in seen:
            continue
        seen.add(canonical_key)
        unique_keys.append(key)

    if not unique_keys:
        return result

    key_index_by_name = {column.name.lower(): index for index, column in enumerate(columns)}
    key_indexes = [key_index_by_name[column.name.lower()] for column in primary_key_columns]
    selected = ", ".join(adapter.quote_identifier(column.name) for column in columns)
    # Bound both the parameter count (SQL Server: 2100) and OR-expression depth.
    keys_per_query = max(1, min(100, 900 // len(primary_key_columns)))
    cursor = connection.cursor()
    try:
        for offset in range(0, len(unique_keys), keys_per_query):
            _check_cancel(cancel)
            key_batch = unique_keys[offset:offset + keys_per_query]
            predicates = []
            params = []
            for raw_key in key_batch:
                parts = []
                for column, value in zip(primary_key_columns, raw_key):
                    parts.append(f"{adapter.quote_identifier(column.name)} = {adapter.placeholder(len(params))}")
                    params.append(value)
                predicates.append("(" + " AND ".join(parts) + ")")
            select_sql = f"SELECT {selected} FROM {adapter.qualified_table(metadata)} WHERE " + " OR ".join(predicates)
            adapter.execute(cursor, select_sql, tuple(params))
            for row in cursor.fetchall():
                row_tuple = tuple(row)
                result[_sync_key_from_row(row_tuple, key_indexes, primary_key_columns)] = row_tuple
    finally:
        _close_cursor(cursor)
    return result


def _sync_key_from_row(
    row: Sequence[object],
    key_indexes: list[int],
    key_columns: list[DatabaseColumn],
) -> tuple[object, ...]:
    return _sync_key_from_values((row[index] for index in key_indexes), key_columns)


def _sync_key_from_values(values: Iterable[object], key_columns: list[DatabaseColumn]) -> tuple[object, ...]:
    return tuple(_sync_sort_value(value, column) for value, column in zip(values, key_columns))


def _next_ordered_sync_row(
    iterator,
    previous_key,
    key_indexes: list[int],
    key_columns: list[DatabaseColumn],
    side_label: str,
):
    try:
        row = next(iterator)
    except StopIteration:
        return None, previous_key
    key = tuple(
        _sync_sort_value(row[index], column)
        for index, column in zip(key_indexes, key_columns)
    )
    if previous_key is not None and key <= previous_key:
        raise ValueError(
            f"Thứ tự primary key ở CSDL {side_label} không tương thích để đồng bộ streaming. "
            "Hãy kiểm tra datatype/collation của primary key giữa hai CSDL."
        )
    return (row, key), key


def _sync_sort_value(value: object, column: DatabaseColumn):
    if value is None:
        raise ValueError(f"Primary key {column.name} có giá trị NULL.")
    canonical = _canonical_sync_value(value, column)
    if isinstance(canonical, Decimal):
        return 0, canonical
    return 1, str(canonical)


def _canonical_sync_value(value: object, column: DatabaseColumn):
    if value is None:
        return None
    if column.is_number_export:
        try:
            if isinstance(value, bool):
                return Decimal(int(value))
            number = Decimal(str(value))
            if number.is_finite():
                return number.normalize()
        except (InvalidOperation, ValueError):
            pass
    if column.is_datetime_export:
        if isinstance(value, datetime):
            return _format_datetime(value)
        return _format_datetime_text(str(value))
    if column.is_time_export:
        if isinstance(value, time):
            return _format_time(value)
        return _format_time_text(str(value))
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    if isinstance(value, memoryview):
        return bytes(value).hex()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _close_cursor(cursor) -> None:
    close = getattr(cursor, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _build_sync_columns(
    source_metadata: TableMetadata,
    target_metadata: TableMetadata,
    target_adapter: DatabaseAdapter,
    keep_identity: bool,
) -> tuple[list[DatabaseColumn], list[DatabaseColumn], tuple[str, ...]]:
    source_by_exact = {column.name: column for column in source_metadata.columns}
    source_by_lower: dict[str, list[DatabaseColumn]] = {}
    for column in source_metadata.columns:
        source_by_lower.setdefault(column.name.lower(), []).append(column)

    target_by_lower = {column.name.lower() for column in target_metadata.columns}
    missing_in_target = [
        column.name
        for column in source_metadata.columns
        if not _skip_insert_reason(column, target_adapter, keep_identity) and column.name.lower() not in target_by_lower
    ]

    source_columns: list[DatabaseColumn] = []
    target_columns: list[DatabaseColumn] = []
    skipped_columns: list[str] = []
    missing_in_source: list[str] = []

    for target_column in target_metadata.columns:
        skip_reason = _skip_insert_reason(target_column, target_adapter, keep_identity)
        if skip_reason:
            skipped_columns.append(f"{target_column.name} ({skip_reason})")
            continue

        source_column = source_by_exact.get(target_column.name)
        if source_column is None:
            candidates = source_by_lower.get(target_column.name.lower(), [])
            if len(candidates) == 1:
                source_column = candidates[0]
        if source_column is None:
            missing_in_source.append(target_column.name)
            continue

        source_columns.append(source_column)
        target_columns.append(target_column)

    if missing_in_source or missing_in_target:
        detail_parts: list[str] = []
        if missing_in_source:
            detail_parts.append("thiếu ở nguồn: " + ", ".join(missing_in_source))
        if missing_in_target:
            detail_parts.append("thiếu ở đích: " + ", ".join(missing_in_target))
        raise ValueError("DDL/column giữa nguồn và đích không khớp (" + "; ".join(detail_parts) + ")")

    return source_columns, target_columns, tuple(skipped_columns)


def _build_sync_select_sql(
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    columns: list[DatabaseColumn],
    order_columns: list[DatabaseColumn] | None = None,
    where_clause: str = "",
) -> str:
    column_sql = ", ".join(adapter.quote_identifier(column.name) for column in columns)
    sql = f"SELECT {column_sql} FROM {adapter.qualified_table(metadata)}"
    normalized_where_clause = _normalize_sync_where_clause(where_clause)
    if normalized_where_clause:
        sql = f"{sql} WHERE ({normalized_where_clause})"
    primary_key_columns = order_columns or [column for column in metadata.columns if column.is_primary_key]
    if primary_key_columns:
        order_sql = ", ".join(adapter.quote_identifier(column.name) for column in primary_key_columns)
        sql = f"{sql} ORDER BY {order_sql}"
    return sql


def _build_column_mapping(headers: list[str], columns: list[DatabaseColumn]) -> CsvColumnMapping:
    if len(headers) != len(set(headers)):
        raise ValueError("CSV có header cột bị trùng.")

    db_by_exact = {column.name: column for column in columns}
    db_by_lower: dict[str, list[DatabaseColumn]] = {}
    for column in columns:
        db_by_lower.setdefault(column.name.lower(), []).append(column)

    csv_index_by_db_name: dict[str, int] = {}
    missing_headers: list[str] = []
    for index, header in enumerate(headers):
        column = db_by_exact.get(header)
        if column is None:
            candidates = db_by_lower.get(header.lower(), [])
            if len(candidates) == 1:
                column = candidates[0]
        if column is None:
            missing_headers.append(header)
            continue
        csv_index_by_db_name[column.name] = index

    if missing_headers:
        raise ValueError("Cột CSV không tồn tại trong table CSDL: " + ", ".join(missing_headers))

    mapped_columns = [column for column in columns if column.name in csv_index_by_db_name]
    return CsvColumnMapping(csv_index_by_db_name=csv_index_by_db_name, columns=mapped_columns)


def _build_import_mapping(
    table: DbeaverCsv,
    columns: list[DatabaseColumn],
    adapter: DatabaseAdapter,
    keep_identity: bool,
) -> CsvColumnMapping:
    mapping = _build_column_mapping(table.headers, columns)
    insert_columns: list[DatabaseColumn] = []
    skipped_columns: list[str] = []

    for column in mapping.columns:
        skip_reason = _skip_insert_reason(column, adapter, keep_identity)
        if skip_reason:
            skipped_columns.append(f"{column.name} ({skip_reason})")
            continue
        insert_columns.append(column)

    return CsvColumnMapping(
        csv_index_by_db_name=mapping.csv_index_by_db_name,
        columns=insert_columns,
        skipped_columns=tuple(skipped_columns),
    )


def _skip_insert_reason(column: DatabaseColumn, adapter: DatabaseAdapter, keep_identity: bool) -> str:
    if column.is_generated:
        return "computed/generated"
    if column.is_rowversion:
        return "rowversion/timestamp"
    if column.is_identity and not keep_identity:
        return "identity được CSDL tự sinh"
    if column.is_identity and keep_identity and not adapter.can_keep_identity(column):
        return "CSDL không cho nhập identity GENERATED ALWAYS"
    return ""


def _build_export_select_sql(adapter: DatabaseAdapter, metadata: TableMetadata, columns: list[DatabaseColumn]) -> str:
    column_sql = ", ".join(adapter.quote_identifier(column.name) for column in columns)
    sql = f"SELECT {column_sql} FROM {adapter.qualified_table(metadata)}"
    primary_key_columns = [column for column in columns if column.is_primary_key]
    if primary_key_columns:
        order_sql = ", ".join(adapter.quote_identifier(column.name) for column in primary_key_columns)
        sql = f"{sql} ORDER BY {order_sql}"
    return sql


def _format_csv_value(value: str | None, column: DatabaseColumn) -> str | None:
    if value is None or value == "":
        return value
    if column.is_datetime_export:
        return _format_datetime_text(value)
    if column.is_time_export:
        return _format_time_text(value)
    if column.is_decimal_export:
        return _format_four_decimal_text(value)
    return value


def _format_db_value(value: object, column: DatabaseColumn) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, time):
        return _format_time(value)
    if isinstance(value, date):
        return f"{value:%Y-%m-%d}"
    if isinstance(value, Decimal):
        return _format_decimal(value, column)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _canonical_hash_value(value: object, column: DatabaseColumn) -> dict[str, str | None]:
    formatted = _format_db_value(value, column)
    return {"type": column.normalized_type_name, "value": formatted}


def _format_datetime_text(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value
    return _format_datetime(parsed)


def _format_time_text(value: str) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return value
    return _format_time(parsed)


def _format_four_decimal_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return value
    try:
        number = Decimal(stripped)
    except InvalidOperation:
        return value
    if not number.is_finite():
        return value
    try:
        return format(number.quantize(CSV_DECIMAL_QUANT, rounding=ROUND_HALF_UP), "f")
    except InvalidOperation:
        return value


def _format_datetime(value: datetime) -> str:
    formatted = f"{value:%Y-%m-%d %H:%M:%S}.{value.microsecond // 1000:03d}"
    if value.tzinfo is not None:
        offset = value.strftime("%z")
        if offset:
            formatted = f"{formatted} {offset[:3]}:{offset[3:]}"
    return formatted


def _format_time(value: time) -> str:
    return f"{value:%H:%M:%S}.{value.microsecond // 1000:03d}"


def _format_decimal(value: Decimal, column: DatabaseColumn) -> str:
    scale = column.numeric_scale
    if scale is not None and scale >= 0:
        quant = Decimal(1).scaleb(-scale)
        try:
            return format(value.quantize(quant), "f")
        except InvalidOperation:
            return format(value, "f")
    return format(value, "f")


def _parse_datetime(value: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None
    iso_value = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        pass

    formats = (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M:%S.%f",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M:%S.%f %p",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%d/%m/%Y %H:%M:%S.%f",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %I:%M:%S.%f %p",
        "%d/%m/%Y %I:%M:%S %p",
        "%d/%m/%Y %I:%M %p",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    )
    for date_format in formats:
        try:
            return datetime.strptime(stripped, date_format)
        except ValueError:
            continue

    try:
        parsed_date = date.fromisoformat(stripped)
        return datetime.combine(parsed_date, time())
    except ValueError:
        return None


def _parse_time(value: str) -> time | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return time.fromisoformat(stripped)
    except ValueError:
        pass

    formats = ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M", "%I:%M:%S.%f %p", "%I:%M:%S %p", "%I:%M %p")
    for time_format in formats:
        try:
            return datetime.strptime(stripped, time_format).time()
        except ValueError:
            continue
    return None


def _parse_table_names(table_names: Iterable[str] | str | None) -> list[str]:
    if table_names is None:
        return []
    if isinstance(table_names, str):
        return [name.strip() for name in re.split(r"[,;\r\n]+", table_names) if name.strip()]
    return [name.strip() for name in table_names if name.strip()]


def _parse_record_limit(record_limit: int | str | None) -> int | None:
    if record_limit is None:
        return None
    if isinstance(record_limit, int):
        if record_limit <= 0:
            raise ValueError("Số record đồng bộ phải lớn hơn 0.")
        return record_limit

    stripped = record_limit.strip()
    if not stripped:
        return None
    try:
        limit = int(stripped)
    except ValueError as exc:
        raise ValueError("Số record đồng bộ phải là số nguyên lớn hơn 0.") from exc
    if limit <= 0:
        raise ValueError("Số record đồng bộ phải lớn hơn 0.")
    return limit


def _validate_sync_mode(value: str | None, truncate_before_sync: bool = False) -> str:
    if value is None or not str(value).strip():
        return SYNC_MODE_TRUNCATE_TABLE if truncate_before_sync else SYNC_MODE_APPEND
    normalized = str(value).strip().lower()
    if normalized not in SYNC_MODES:
        raise ValueError(f"Chế độ đồng bộ dữ liệu không hợp lệ: {value}")
    return normalized


def _validate_sync_duplicate_mode(value: str | None) -> str:
    normalized = str(value or SYNC_DUPLICATE_ERROR).strip().lower()
    if normalized not in SYNC_DUPLICATE_MODES:
        raise ValueError(f"Chế độ xử lý trùng key khi đồng bộ không hợp lệ: {value}")
    return normalized


def _normalize_sync_where_clause(value: str | None) -> str:
    clause = str(value or "").strip()
    if not clause:
        return ""
    if clause[:5].casefold() == "where" and (len(clause) == 5 or clause[5].isspace()):
        clause = clause[5:].strip()
    forbidden_tokens = (";", "--", "/*", "*/", "\x00")
    if any(token in clause for token in forbidden_tokens):
        raise ValueError("Điều kiện WHERE không được chứa dấu ; hoặc comment SQL.")
    return clause


def _parse_sync_batch_size(value: int | str | None) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return DEFAULT_SYNC_BATCH_SIZE
    try:
        batch_size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Batch size phải là số nguyên.") from exc
    if not MIN_SYNC_BATCH_SIZE <= batch_size <= MAX_SYNC_BATCH_SIZE:
        raise ValueError(
            f"Batch size phải nằm trong khoảng {MIN_SYNC_BATCH_SIZE} đến {MAX_SYNC_BATCH_SIZE}."
        )
    return batch_size


def _split_table_name(raw_table_name: str) -> tuple[str | None, str]:
    parts = [part.strip().strip('"[]`') for part in raw_table_name.split(".") if part.strip()]
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return None, parts[0]


def _export_file_name(metadata: TableMetadata, include_schema: bool) -> str:
    if include_schema:
        return f"{metadata.schema}.{metadata.name}.csv"
    return f"{metadata.name}.csv"


def _prepare_sync_backup_dir(table_names: Sequence[str], backup_root: str | Path | None = None) -> Path:
    root = Path(backup_root) if backup_root is not None else Path.cwd() / "db_sync_backups"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if len(table_names) == 1:
        label = _safe_path_name(table_names[0])
    else:
        label = f"multi_tables_{len(table_names)}"
    backup_dir = root / f"{timestamp}_{label}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    return backup_dir


def _open_sync_backup_writer(
    backup_dir: Path | None,
    metadata: TableMetadata,
    columns: list[DatabaseColumn],
) -> TypedDbeaverCsvRowWriter | None:
    if backup_dir is None:
        return None
    backup_file = backup_dir / f"{_safe_path_name(metadata.schema)}.{_safe_path_name(metadata.name)}.csv"
    headers = [column.name for column in columns]
    quote_columns = [column.should_quote_export for column in columns]
    return TypedDbeaverCsvRowWriter(backup_file, headers, quote_columns)


def _safe_path_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value).strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or "table"


def _iter_csv_files(root: Path) -> list[Path]:
    return sorted((path for path in root.rglob("*.csv") if path.is_file()), key=lambda path: str(path).lower())


def _iter_direct_csv_files(root: Path) -> list[Path]:
    return sorted((path for path in root.glob("*.csv") if path.is_file()), key=lambda path: str(path).lower())


def _validate_folder(path_value: str | Path, must_exist: bool) -> Path:
    path = Path(path_value).expanduser().resolve()
    if must_exist:
        if not path.exists():
            raise FileNotFoundError(f"Folder không tồn tại: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"Đường dẫn không phải là folder: {path}")
    else:
        if path.exists() and not path.is_dir():
            raise NotADirectoryError(f"Đường dẫn xuất không phải là folder: {path}")
        path.mkdir(parents=True, exist_ok=True)
    return path


def _record_skip(summary: DatabaseCsvSummary, logger: Logger, table: str, reason: str, message: str) -> None:
    summary.skipped.append(message)
    summary.skipped_items.append(DatabaseCsvIssue(table, reason))
    logger(message)


def _record_error(
    summary: DatabaseCsvSummary, logger: Logger, path: Path | str, exc: Exception, *, table: str | None = None,
) -> None:
    message = f"LỖI {path}: {exc}"
    summary.errors.append(message)
    if table is not None:
        summary.failed.append(DatabaseCsvIssue(table, str(exc)))
    logger(message)


def _log_summary(summary: DatabaseCsvSummary, logger: Logger, *, include_items: bool = False) -> None:
    logger(
        f"{summary.action_name} hoàn tất. "
        f"Xử lý {summary.csv_count} file CSV, {summary.row_count} dòng, "
        f"bỏ qua {len(summary.skipped)} mục, lỗi {summary.error_count} mục."
    )
    if include_items:
        logger("===== Tổng kết =====")
        successes = ", ".join(f"{item.table} ({item.row_count} dòng)" for item in summary.succeeded)
        logger(f"Thành công ({len(summary.succeeded)}): {successes}" if successes else "Thành công (0)")
        for label, items in (("Lỗi", summary.failed), ("Bỏ qua", summary.skipped_items)):
            if not items:
                logger(f"{label} (0)")
                continue
            for index, item in enumerate(items):
                detail = f"{item.table} — {item.message}" if item.table else item.message
                logger(f"{label} ({len(items)}): {detail}" if index == 0 else f"  {detail}")


def _log_sync_summary(summary: DatabaseSyncSummary, logger: Logger) -> None:
    logger(
        f"{summary.action_name} hoàn tất. "
        f"Xử lý {summary.table_count} table, {summary.row_count} thay đổi "
        f"(insert {summary.inserted_count}, update {summary.updated_count}, delete {summary.deleted_count}), "
        f"bỏ qua {len(summary.skipped)} mục, lỗi {summary.error_count} mục."
    )


def _relative_to(path: Path, folder: Path) -> Path:
    try:
        return path.relative_to(folder)
    except ValueError:
        return path


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _server_with_port(host: str, port: str) -> str:
    if not port:
        return host
    if "," in host or ":" in host:
        return host
    return f"{host},{port}"


def _sqlserver_type_name(value: object) -> str:
    type_name = str(value)
    if type_name.lower() == "timestamp":
        return "rowversion"
    return type_name


def _brace_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def _description_type_name(item: Sequence[object]) -> str:
    if len(item) < 2 or item[1] is None:
        return "unknown"
    value = item[1]
    return getattr(value, "__name__", None) or str(value)


def _description_nullable(item: Sequence[object]) -> bool:
    if len(item) < 7 or item[6] is None:
        return True
    return bool(item[6])
