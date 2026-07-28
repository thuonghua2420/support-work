from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable

from .dbeaver_csv import DbeaverCsv, read_dbeaver_csv, write_dbeaver_csv

Logger = Callable[[str], None]

ODBC_DRIVER_DEFAULT = "ODBC Driver 18 for SQL Server"
FOUR_DECIMAL_QUANT = Decimal("0.0001")

DATETIME_TYPE_NAMES = {"datetime", "datetime2", "smalldatetime"}
DATETIMEOFFSET_TYPE_NAMES = {"datetimeoffset"}
TIME_TYPE_NAMES = {"time"}
FOUR_DECIMAL_TYPE_NAMES = {"decimal", "numeric", "money", "smallmoney"}

DATETIME_PARSE_FORMATS = (
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

TIME_PARSE_FORMATS = (
    "%H:%M:%S.%f",
    "%H:%M:%S",
    "%H:%M",
    "%I:%M:%S.%f %p",
    "%I:%M:%S %p",
    "%I:%M %p",
)


class TableNotFoundError(LookupError):
    pass


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
    system_type_name: str = ""

    @property
    def insertable(self) -> bool:
        return (
            not self.is_computed
            and self.generated_always_type == 0
            and self.type_name.lower() not in {"timestamp", "rowversion"}
        )

    @property
    def normalized_type_name(self) -> str:
        return (self.system_type_name or self.type_name).lower()

    @property
    def is_datetime_export(self) -> bool:
        return self.normalized_type_name in DATETIME_TYPE_NAMES | DATETIMEOFFSET_TYPE_NAMES

    @property
    def is_time_export(self) -> bool:
        return self.normalized_type_name in TIME_TYPE_NAMES

    @property
    def is_four_decimal_export(self) -> bool:
        return self.normalized_type_name in FOUR_DECIMAL_TYPE_NAMES


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

    connection = _connect(settings)
    try:
        result = _process_csv_folder(connection, settings, root, logger)
        summary.cases.append(result)
        summary.errors.extend(result.errors)
    finally:
        connection.close()

    logger("DB CSV normalization done.")
    return summary


def _process_csv_folder(
    connection,
    settings: DatabaseSettings,
    folder: Path,
    log: Logger,
) -> CaseRoundtripResult:
    result = CaseRoundtripResult(case_path=folder)
    log(f"[{folder.name}] Scan {folder}")

    csv_files = sorted(folder.rglob("*.csv"), key=lambda path: str(path).lower())
    if not csv_files:
        log(f"[{folder.name}] No CSV files found.")
        return result

    for csv_path in csv_files:
        relative_csv_path = _relative_to(csv_path, folder)
        try:
            table = read_dbeaver_csv(csv_path)
            if not table.headers:
                log(f"[{folder.name}] {relative_csv_path} -> skipped empty CSV")
                continue

            table_name = csv_path.stem
            columns = _get_table_columns(connection, settings.schema, table_name)
            ordered_headers, ordered_rows = _reorder_csv_by_db_columns(table, columns)
            write_dbeaver_csv(csv_path, ordered_headers, ordered_rows)

            result.csv_results.append(
                CsvRoundtripResult(csv_path=csv_path, table_name=table_name, row_count=len(table.rows))
            )
            log(
                f"[{folder.name}] {relative_csv_path} -> "
                f"{table_name} normalized ({len(table.rows)} row(s))"
            )
        except TableNotFoundError:
            log(f"[{folder.name}] {relative_csv_path} -> skipped table not found: {settings.schema}.{csv_path.stem}")
        except Exception as exc:
            connection.rollback()
            message = f"[{folder.name}] ERROR {csv_path}: {exc}"
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
            TYPE_NAME(c.system_type_id) AS system_type_name,
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
            system_type_name=row.system_type_name,
        )
        for row in cursor.fetchall()
    ]
    if not columns:
        raise TableNotFoundError(f"Table not found: {schema}.{table_name}")
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
        [
            _format_output_value(row[mapping.csv_index_by_db_name[column.name]], column)
            for column in mapping.export_columns
        ]
        for row in table.rows
    ]
    return ordered_headers, ordered_rows


def _format_output_value(value: str | None, column: TableColumn) -> str | None:
    if value is None or value == "":
        return value
    if column.is_datetime_export:
        return _format_datetime_value(value, include_offset=column.normalized_type_name in DATETIMEOFFSET_TYPE_NAMES)
    if column.is_time_export:
        return _format_time_value(value)
    if column.is_four_decimal_export:
        return _format_four_decimal_value(value)
    return value


def _format_datetime_value(value: str, include_offset: bool = False) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value

    formatted = f"{parsed:%Y-%m-%d %H:%M:%S}.{parsed.microsecond // 1000:03d}"
    if include_offset and parsed.tzinfo is not None:
        offset = parsed.strftime("%z")
        if offset:
            formatted = f"{formatted} {offset[:3]}:{offset[3:]}"
    return formatted


def _format_time_value(value: str) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return value
    return f"{parsed:%H:%M:%S}.{parsed.microsecond // 1000:03d}"


def _format_four_decimal_value(value: str) -> str:
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
        return format(number.quantize(FOUR_DECIMAL_QUANT, rounding=ROUND_HALF_UP), "f")
    except InvalidOperation:
        return value


def _parse_datetime(value: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None

    iso_value = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        pass

    for date_format in DATETIME_PARSE_FORMATS:
        try:
            parsed = datetime.strptime(stripped, date_format)
            if isinstance(parsed, datetime):
                return parsed
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

    for time_format in TIME_PARSE_FORMATS:
        try:
            return datetime.strptime(stripped, time_format).time()
        except ValueError:
            continue
    return None


def _relative_to(path: Path, folder: Path) -> Path:
    try:
        return path.relative_to(folder)
    except ValueError:
        return path


def _quote_identifier(value: str) -> str:
    return "[" + value.replace("]", "]]") + "]"


def _qualified_table(schema: str, table: str) -> str:
    return f"{_quote_identifier(schema)}.{_quote_identifier(table)}"
