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


def build_sheet_comparison(name: str, before: CsvTable, after: CsvTable) -> SheetComparison:
    columns = _union_headers(before.headers, after.headers)
    before_keyed = _key_rows(before)
    after_keyed = _key_rows(after)

    before_by_key = {key: row for key, row in before_keyed}
    pairs: list[RecordPair] = []
    used_before_keys: set[tuple[str | None, int]] = set()

    for key, after_row in after_keyed:
        before_row = before_by_key.get(key)
        pairs.append(RecordPair(before=before_row, after=after_row))
        if before_row is not None:
            used_before_keys.add(key)

    for key, before_row in before_keyed:
        if key not in used_before_keys:
            pairs.append(RecordPair(before=before_row, after=None))

    return SheetComparison(
        name=name,
        before_headers=before.headers,
        after_headers=after.headers,
        columns=columns,
        pairs=pairs,
    )


def _union_headers(before_headers: list[str], after_headers: list[str]) -> list[str]:
    columns = [header for header in after_headers if header not in SKIP_COLUMN_NAMES]
    for header in before_headers:
        if header not in SKIP_COLUMN_NAMES and header not in columns:
            columns.append(header)
    return columns


def _key_rows(table: CsvTable) -> list[tuple[tuple[str | None, int], dict[str, str | None]]]:
    if not table.headers:
        return [((f"__row_{index}", 0), row) for index, row in enumerate(table.rows)]

    key_header = table.headers[0]
    occurrence_by_value: dict[str | None, int] = {}
    keyed_rows: list[tuple[tuple[str | None, int], dict[str, str | None]]] = []

    for row in table.rows:
        key_value = row.get(key_header, "")
        occurrence = occurrence_by_value.get(key_value, 0)
        occurrence_by_value[key_value] = occurrence + 1
        keyed_rows.append(((key_value, occurrence), row))

    return keyed_rows


def cell_value(row: dict[str, str | None] | None, column: str) -> str:
    if row is None:
        return ""
    value = row.get(column, "")
    return "NULL" if value is None else value
