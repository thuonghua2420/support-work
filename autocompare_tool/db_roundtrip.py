from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .constants import AFTER_NEW_DIR, OUTPUT_DIR
from .dbeaver_csv import DbeaverCsv, read_dbeaver_csv, write_dbeaver_csv
from .processor import discover_test_cases

Logger = Callable[[str], None]

ODBC_DRIVER_DEFAULT = "ODBC Driver 18 for SQL Server"


@dataclass(frozen=True)
class DatabaseSettings:
    server: str
    database: str
    driver: str = ODBC_DRIVER_DEFAULT
    trusted_connection: bool = True
    username: str = ""
    password: str = ""
    trust_server_certificate: bool = True
    encrypt: bool = True
    schema: str = "dbo"


@dataclass(frozen=True)
class TableColumn:
    name: str
    column_id: int
    is_identity: bool
    is_computed: bool
    generated_always_type: int
    type_name: str
    is_primary_key: bool

    @property
    def insertable(self) -> bool:
        return (
            not self.is_computed
            and self.generated_always_type == 0
            and self.type_name.lower() not in {"timestamp", "rowversion"}
        )


@dataclass(frozen=True)
class ColumnMapping:
    csv_index_by_db_name: dict[str, int]
    export_columns: list[TableColumn]


@dataclass
class CsvRoundtripResult:
    csv_path: Path
    table_name: str
    row_count: int


@dataclass
class CaseRoundtripResult:
    case_path: Path
    csv_results: list[CsvRoundtripResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class DatabaseRoundtripSummary:
    root_path: Path
    cases: list[CaseRoundtripResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def csv_count(self) -> int:
        return sum(len(case.csv_results) for case in self.cases)


def get_available_sql_drivers() -> list[str]:
    try:
        import pyodbc
    except ImportError:
        return []
    return list(pyodbc.drivers())


def test_sqlserver_connection(settings: DatabaseSettings) -> None:
    connection = _connect(settings)
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
    finally:
        connection.close()


def process_sqlserver_roundtrip(
    root_path: str | Path,
    settings: DatabaseSettings,
    log: Logger | None = None,
) -> DatabaseRoundtripSummary:
    root = Path(root_path).expanduser().resolve()
    logger = log or (lambda message: None)

    if not root.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Root path is not a folder: {root}")

    summary = DatabaseRoundtripSummary(root_path=root)
    test_cases = discover_test_cases(root)
    if not test_cases:
        message = f"No UT* test case folders found under: {root}"
        summary.errors.append(message)
        logger(message)
        return summary

    connection = _connect(settings)
    try:
        for case_path in test_cases:
            case_result = _process_case(connection, settings, case_path, logger)
            summary.cases.append(case_result)
            summary.errors.extend(case_result.errors)
    finally:
        connection.close()

    logger("DB column-order normalization done.")
    return summary


def _process_case(
    connection,
    settings: DatabaseSettings,
    case_path: Path,
    log: Logger,
) -> CaseRoundtripResult:
    result = CaseRoundtripResult(case_path=case_path)
    after_new_dir = case_path / OUTPUT_DIR / AFTER_NEW_DIR
    log(f"[{case_path.name}] Scan {after_new_dir}")

    if not after_new_dir.exists() or not after_new_dir.is_dir():
        message = f"[{case_path.name}] Missing folder: {after_new_dir}"
        result.errors.append(message)
        log(message)
        return result

    csv_files = sorted(after_new_dir.rglob("*.csv"), key=lambda path: str(path).lower())
    if not csv_files:
        log(f"[{case_path.name}] No CSV files found.")
        return result

    for csv_path in csv_files:
        try:
            table = read_dbeaver_csv(csv_path)
            if not table.headers:
                log(f"[{case_path.name}] {csv_path.relative_to(after_new_dir)} -> skipped empty CSV")
                continue

            table_name = csv_path.stem
            columns = _get_table_columns(connection, settings.schema, table_name)
            ordered_headers, ordered_rows = _reorder_csv_by_db_columns(table, columns)
            write_dbeaver_csv(csv_path, ordered_headers, ordered_rows)

            result.csv_results.append(
                CsvRoundtripResult(csv_path=csv_path, table_name=table_name, row_count=len(table.rows))
            )
            log(
                f"[{case_path.name}] {csv_path.relative_to(after_new_dir)} -> "
                f"{table_name} column order normalized ({len(table.rows)} row(s))"
            )
        except Exception as exc:
            connection.rollback()
            message = f"[{case_path.name}] ERROR {csv_path}: {exc}"
            result.errors.append(message)
            log(message)

    return result


def _connect(settings: DatabaseSettings):
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("pyodbc is not installed. Run run.bat to install dependencies.") from exc

    parts = [
        f"DRIVER={_brace_value(settings.driver)}",
        f"SERVER={_brace_value(settings.server)}",
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


def _brace_value(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def _get_table_columns(connection, schema: str, table_name: str) -> list[TableColumn]:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            c.name,
            c.column_id,
            c.is_identity,
            c.is_computed,
            c.generated_always_type,
            ty.name AS type_name,
            CASE WHEN pk.column_id IS NULL THEN CONVERT(bit, 0) ELSE CONVERT(bit, 1) END AS is_primary_key
        FROM sys.schemas s
        INNER JOIN sys.tables tb ON tb.schema_id = s.schema_id
        INNER JOIN sys.columns c ON c.object_id = tb.object_id
        INNER JOIN sys.types ty ON ty.user_type_id = c.user_type_id
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
        WHERE s.name = ? AND tb.name = ?
        ORDER BY c.column_id
        """,
        schema,
        table_name,
    )
    columns = [
        TableColumn(
            name=row.name,
            column_id=int(row.column_id),
            is_identity=bool(row.is_identity),
            is_computed=bool(row.is_computed),
            generated_always_type=int(row.generated_always_type),
            type_name=row.type_name,
            is_primary_key=bool(row.is_primary_key),
        )
        for row in cursor.fetchall()
    ]
    if not columns:
        raise ValueError(f"Table not found: {schema}.{table_name}")
    return columns


def _build_column_mapping(headers: list[str], columns: list[TableColumn]) -> ColumnMapping:
    if len(headers) != len(set(headers)):
        raise ValueError("CSV has duplicate column headers.")

    db_by_exact = {column.name: column for column in columns}
    db_by_lower: dict[str, list[TableColumn]] = {}
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
        raise ValueError("CSV column(s) not found in DB table: " + ", ".join(missing_headers))

    export_columns = [column for column in columns if column.name in csv_index_by_db_name]

    return ColumnMapping(
        csv_index_by_db_name=csv_index_by_db_name,
        export_columns=export_columns,
    )


def _reorder_csv_by_db_columns(table: DbeaverCsv, columns: list[TableColumn]) -> tuple[list[str], list[list[str | None]]]:
    mapping = _build_column_mapping(table.headers, columns)
    ordered_headers = [column.name for column in mapping.export_columns]
    ordered_rows = [
        [row[mapping.csv_index_by_db_name[column.name]] for column in mapping.export_columns]
        for row in table.rows
    ]
    return ordered_headers, ordered_rows


def _quote_identifier(value: str) -> str:
    return "[" + value.replace("]", "]]") + "]"


def _qualified_table(schema: str, table: str) -> str:
    return f"{_quote_identifier(schema)}.{_quote_identifier(table)}"
