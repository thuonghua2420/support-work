from __future__ import annotations

from dataclasses import dataclass

from .csv_table import CsvTable

SKIP_COLUMN_NAMES = {"ValidationErrors", "HasErrors", "TargetProperties", "DataState"}


@dataclass(frozen=True)
class RecordPair:
    before: dict[str, str | None] | None
    after: dict[str, str | None] | None


@dataclass(frozen=True)
class SheetComparison:
    name: str
    before_headers: list[str]
    after_headers: list[str]
    columns: list[str]
    pairs: list[RecordPair]


def build_sheet_comparison(
    name: str, before: CsvTable, after: CsvTable,
) -> SheetComparison:
    columns = _union_headers(before.headers, after.headers)

    return SheetComparison(
        name=name,
        before_headers=before.headers,
        after_headers=after.headers,
        columns=columns,
        pairs=_pair_by_record_order(before.rows, after.rows),
    )


def _pair_by_record_order(
    before_rows: list[dict[str, str | None]],
    after_rows: list[dict[str, str | None]],
) -> list[RecordPair]:
    pairs: list[RecordPair] = []
    max_rows = max(len(before_rows), len(after_rows))

    for index in range(max_rows):
        before_row = before_rows[index] if index < len(before_rows) else None
        after_row = after_rows[index] if index < len(after_rows) else None
        pairs.append(RecordPair(before=before_row, after=after_row))

    return pairs


def _union_headers(before_headers: list[str], after_headers: list[str]) -> list[str]:
    columns = [header for header in after_headers if header not in SKIP_COLUMN_NAMES]
    for header in before_headers:
        if header not in SKIP_COLUMN_NAMES and header not in columns:
            columns.append(header)
    return columns


def cell_value(row: dict[str, str | None] | None, column: str) -> str:
    if row is None:
        return ""
    value = row.get(column, "")
    return "NULL" if value is None else value


def cell_values_equal(
    before_row: dict[str, str | None] | None,
    after_row: dict[str, str | None] | None,
    column: str,
) -> bool:
    """Compare CSV cells without collapsing distinct source representations."""
    if before_row is None or after_row is None:
        return before_row is after_row
    if (column in before_row) != (column in after_row):
        return False
    if column not in before_row:
        return True
    return before_row[column] == after_row[column]
