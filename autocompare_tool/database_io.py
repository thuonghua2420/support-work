from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .dbeaver_csv import DbeaverCsv, read_dbeaver_csv, write_dbeaver_csv, write_typed_dbeaver_csv

Logger = Callable[[str], None]

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
SYNC_MODES = {
    SYNC_MODE_APPEND,
    SYNC_MODE_INCREMENTAL,
    SYNC_MODE_TRUNCATE_TABLE,
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
    encrypt: bool = True

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


@dataclass(frozen=True)
class CsvDbResult:
    csv_path: Path
    table_name: str
    row_count: int
    skipped_columns: tuple[str, ...] = ()


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


@dataclass
class DatabaseCsvSummary:
    action_name: str
    root_path: Path
    csv_results: list[CsvDbResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

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


@dataclass(frozen=True)
class CsvColumnMapping:
    csv_index_by_db_name: dict[str, int]
    columns: list[DatabaseColumn]
    skipped_columns: tuple[str, ...] = ()


class DatabaseAdapter:
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

    def get_table(
        self,
        connection,
        settings: DatabaseConnectionSettings,
        table_name: str,
        schema: str | None = None,
    ) -> TableMetadata:
        raise NotImplementedError

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

        parts = [
            f"DRIVER={_brace_value(settings.driver)}",
            f"SERVER={_brace_value(_server_with_port(settings.host, settings.port))}",
            f"DATABASE={_brace_value(settings.database)}",
            f"Encrypt={'yes' if settings.encrypt else 'no'}",
            f"TrustServerCertificate={'yes' if settings.trust_server_certificate else 'no'}",
        ]
        if settings.trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={_brace_value(settings.username)}")
            parts.append(f"PWD={_brace_value(settings.password)}")
        return pyodbc.connect(";".join(parts), autocommit=False)

    def execute(self, cursor, sql: str, params: Sequence[object] = ()) -> None:
        cursor.execute(sql, *params)

    def quote_identifier(self, value: str) -> str:
        return "[" + value.replace("]", "]]") + "]"

    def default_schema(self, settings: DatabaseConnectionSettings) -> str:
        return settings.schema.strip() or "dbo"

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


class MySqlAdapter(DatabaseAdapter):
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


def normalize_csv_folder(
    root_path: str | Path,
    settings: DatabaseConnectionSettings,
    log: Logger | None = None,
) -> DatabaseCsvSummary:
    root = _validate_folder(root_path, must_exist=True)
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    logger = log or (lambda message: None)
    summary = DatabaseCsvSummary(action_name="Chuẩn hóa CSV theo CSDL", root_path=root)

    connection = adapter.connect(settings)
    try:
        for csv_path in _iter_csv_files(root):
            _normalize_one_csv(connection, adapter, settings, root, csv_path, summary, logger)
    finally:
        connection.close()

    _log_summary(summary, logger)
    return summary


def import_csv_folder(
    root_path: str | Path,
    settings: DatabaseConnectionSettings,
    keep_identity: bool = False,
    log: Logger | None = None,
    existing_row_mode: str = IMPORT_MODE_APPEND,
) -> DatabaseCsvSummary:
    root = _validate_folder(root_path, must_exist=True)
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    logger = log or (lambda message: None)
    existing_row_mode = _validate_import_mode(existing_row_mode)
    summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=root)

    connection = adapter.connect(settings)
    try:
        for csv_path in _iter_csv_files(root):
            _import_one_csv(
                connection,
                adapter,
                settings,
                root,
                csv_path,
                keep_identity,
                summary,
                logger,
                existing_row_mode,
            )
    finally:
        connection.close()

    _log_summary(summary, logger)
    return summary


def export_csv_folder(
    output_path: str | Path,
    settings: DatabaseConnectionSettings,
    table_names: Iterable[str] | str | None = None,
    log: Logger | None = None,
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
        if not tables:
            summary.skipped.append("Không tìm thấy table để xuất.")
            logger("Không tìm thấy table để xuất.")
            return summary

        for raw_table_name in tables:
            _export_one_table(connection, adapter, settings, output, raw_table_name, summary, logger)
    finally:
        connection.close()

    _log_summary(summary, logger)
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
) -> DatabaseSyncSummary:
    source_settings = validate_connection_settings(source_settings)
    target_settings = validate_connection_settings(target_settings)
    source_adapter = get_adapter(source_settings.normalized_type)
    target_adapter = get_adapter(target_settings.normalized_type)
    requested_tables = _parse_table_names(table_names)
    limit = _parse_record_limit(record_limit)
    mode = _validate_sync_mode(sync_mode, truncate_before_sync)
    parsed_batch_size = _parse_sync_batch_size(batch_size)
    if mode == SYNC_MODE_INCREMENTAL and limit is not None:
        raise ValueError(
            "Chế độ đồng bộ chênh lệch không dùng giới hạn record vì có thể bỏ sót record cần xóa ở đích."
        )
    logger = log or (lambda message: None)
    summary = DatabaseSyncSummary()

    source_connection = None
    target_connection = None
    target_read_connection = None
    try:
        source_connection = source_adapter.connect(source_settings)
        target_connection = target_adapter.connect(target_settings)
        target_read_connection = (
            target_adapter.connect(target_settings)
            if mode == SYNC_MODE_INCREMENTAL
            else target_connection
        )
        tables = requested_tables or source_adapter.list_tables(source_connection, source_settings)
        if not tables:
            message = "Không tìm thấy table để đồng bộ."
            summary.skipped.append(message)
            logger(message)
            return summary

        for raw_table_name in tables:
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
                target_read_connection=target_read_connection,
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
) -> None:
    relative_csv_path = _relative_to(csv_path, root)
    try:
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
        write_dbeaver_csv(csv_path, ordered_headers, ordered_rows)
        summary.csv_results.append(
            CsvDbResult(csv_path=csv_path, table_name=metadata.name, row_count=len(table.rows))
        )
        logger(f"{relative_csv_path} -> đã chuẩn hóa theo {metadata.schema}.{metadata.name} ({len(table.rows)} dòng)")
    except TableNotFoundError:
        message = f"{relative_csv_path} -> bỏ qua vì không tìm thấy table: {settings.schema}.{csv_path.stem}"
        summary.skipped.append(message)
        logger(message)
    except Exception as exc:
        _record_error(summary, logger, csv_path, exc)


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
) -> None:
    relative_csv_path = _relative_to(csv_path, root)
    try:
        table = read_dbeaver_csv(csv_path)
        if not table.headers:
            message = f"{relative_csv_path} -> bỏ qua CSV rỗng"
            summary.skipped.append(message)
            logger(message)
            return

        metadata = adapter.get_table(connection, settings, csv_path.stem)
        mapping = _build_import_mapping(table, metadata.columns, adapter, keep_identity)
        if not mapping.columns:
            message = f"{relative_csv_path} -> bỏ qua vì không có column nào có thể nhập"
            summary.skipped.append(message)
            logger(message)
            return

        insert_rows = [
            [row[mapping.csv_index_by_db_name[column.name]] for column in mapping.columns]
            for row in table.rows
        ]
        cursor = connection.cursor()
        insert_sql = adapter.insert_sql(metadata, mapping.columns, keep_identity)
        try:
            _prepare_table_for_import(
                cursor,
                adapter,
                metadata,
                table,
                mapping,
                existing_row_mode,
                relative_csv_path,
                logger,
            )
            adapter.before_import(cursor, metadata, mapping.columns, keep_identity)
            import_error: Exception | None = None
            try:
                if insert_rows:
                    adapter.executemany(cursor, insert_sql, insert_rows)
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
        logger(f"{relative_csv_path} -> đã nhập vào {metadata.schema}.{metadata.name} ({len(insert_rows)} dòng)")
    except TableNotFoundError:
        message = f"{relative_csv_path} -> bỏ qua vì không tìm thấy table: {settings.schema}.{csv_path.stem}"
        summary.skipped.append(message)
        logger(message)
    except Exception as exc:
        _record_error(summary, logger, csv_path, exc)


def _prepare_table_for_import(
    cursor,
    adapter: DatabaseAdapter,
    metadata: TableMetadata,
    table: DbeaverCsv,
    mapping: CsvColumnMapping,
    existing_row_mode: str,
    relative_csv_path: Path,
    logger: Logger,
) -> None:
    mode = _validate_import_mode(existing_row_mode)
    if mode == IMPORT_MODE_APPEND:
        return
    if mode == IMPORT_MODE_TRUNCATE_TABLE:
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
    delete_sql = _build_delete_by_primary_key_sql(adapter, metadata, primary_key_columns)
    adapter.executemany(cursor, delete_sql, key_rows)
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
) -> None:
    schema, table_name = _split_table_name(raw_table_name)
    try:
        metadata = adapter.get_table(connection, settings, table_name, schema=schema)
        columns = metadata.columns
        if not columns:
            message = f"{raw_table_name} -> bỏ qua vì không có column xuất"
            summary.skipped.append(message)
            logger(message)
            return

        cursor = connection.cursor()
        select_sql = _build_export_select_sql(adapter, metadata, columns)
        adapter.execute(cursor, select_sql)
        rows = [
            [_format_db_value(row[index], column) for index, column in enumerate(columns)]
            for row in cursor.fetchall()
        ]
        headers = [column.name for column in columns]
        quote_columns = [column.should_quote_export for column in columns]
        output_file = output / _export_file_name(metadata, schema is not None)
        write_typed_dbeaver_csv(output_file, headers, rows, quote_columns)
        summary.csv_results.append(CsvDbResult(csv_path=output_file, table_name=metadata.name, row_count=len(rows)))
        logger(f"{metadata.schema}.{metadata.name} -> đã xuất {len(rows)} dòng: {output_file}")
    except Exception as exc:
        _record_error(summary, logger, output / f"{raw_table_name}.csv", exc)


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
    target_read_connection=None,
) -> None:
    schema, table_name = _split_table_name(raw_table_name)
    try:
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

        source_cursor = source_connection.cursor()
        source_sql = _build_sync_select_sql(source_adapter, source_metadata, source_columns)
        source_adapter.execute(source_cursor, source_sql)
        rows = source_cursor.fetchmany(record_limit) if record_limit is not None else source_cursor.fetchall()
        insert_rows = [tuple(row[index] for index, _column in enumerate(source_columns)) for row in rows]

        target_cursor = target_connection.cursor()
        insert_sql = target_adapter.insert_sql(target_metadata, target_columns, keep_identity)
        try:
            if mode == SYNC_MODE_TRUNCATE_TABLE:
                target_adapter.truncate_table(target_cursor, target_metadata)
                logger(f"{raw_table_name} -> đã truncate dữ liệu đích trước khi đồng bộ")
            target_adapter.before_import(target_cursor, target_metadata, target_columns, keep_identity)
            sync_error: Exception | None = None
            try:
                if insert_rows:
                    target_adapter.executemany(target_cursor, insert_sql, insert_rows)
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
            target_connection.commit()
        except Exception:
            target_connection.rollback()
            raise

        if skipped_columns:
            logger(f"{raw_table_name} -> bỏ qua column không insert: {', '.join(skipped_columns)}")
        summary.table_results.append(
            DatabaseSyncResult(
                table_name=target_metadata.name,
                row_count=len(insert_rows),
                skipped_columns=tuple(skipped_columns),
                source_row_count=len(insert_rows),
                inserted_count=len(insert_rows),
            )
        )
        logger(f"{raw_table_name} -> đã đồng bộ {len(insert_rows)} dòng vào {target_metadata.schema}.{target_metadata.name}")
    except Exception as exc:
        message = f"LỖI {raw_table_name}: {exc}"
        summary.errors.append(message)
        logger(message)


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
) -> DatabaseSyncResult:
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

    def flush_changes() -> None:
        nonlocal identity_active
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

    try:
        source_adapter.execute(source_cursor, source_sql)
        target_adapter.execute(target_read_cursor, target_sql)
        source_iterator = _iter_cursor_rows(source_cursor, batch_size)
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
        target_write_connection.commit()
    except Exception:
        target_write_connection.rollback()
        raise
    finally:
        _close_cursor(source_cursor)
        _close_cursor(target_read_cursor)
        _close_cursor(target_write_cursor)

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


def _iter_cursor_rows(cursor, batch_size: int):
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            return
        for row in rows:
            yield tuple(row)


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
) -> str:
    column_sql = ", ".join(adapter.quote_identifier(column.name) for column in columns)
    sql = f"SELECT {column_sql} FROM {adapter.qualified_table(metadata)}"
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


def _iter_csv_files(root: Path) -> list[Path]:
    return sorted((path for path in root.rglob("*.csv") if path.is_file()), key=lambda path: str(path).lower())


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


def _record_error(summary: DatabaseCsvSummary, logger: Logger, path: Path, exc: Exception) -> None:
    message = f"LỖI {path}: {exc}"
    summary.errors.append(message)
    logger(message)


def _log_summary(summary: DatabaseCsvSummary, logger: Logger) -> None:
    logger(
        f"{summary.action_name} hoàn tất. "
        f"Xử lý {summary.csv_count} file CSV, {summary.row_count} dòng, "
        f"bỏ qua {len(summary.skipped)} mục, lỗi {summary.error_count} mục."
    )


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
