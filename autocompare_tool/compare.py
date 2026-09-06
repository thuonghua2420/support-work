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
    name: str, before: CsvTable, after: CsvTable, *, pair_by_record_order: bool = False,
) -> SheetComparison:
    columns = _union_headers(before.headers, after.headers)
    before_keyed = _key_rows(before)
    after_keyed = _key_rows(after)

    if pair_by_record_order or _should_pair_by_record_order(before, after, before_keyed, after_keyed):
        pairs = _pair_by_record_order(before.rows, after.rows)
    else:
        pairs = _pair_by_key(before_keyed, after_keyed)

    return SheetComparison(
        name=name,
        before_headers=before.headers,
        after_headers=after.headers,
        columns=columns,
        pairs=pairs,
    )


def _pair_by_key(
    before_keyed: list[tuple[tuple[str | None, int], dict[str, str | None]]],
    after_keyed: list[tuple[tuple[str | None, int], dict[str, str | None]]],
) -> list[RecordPair]:
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

    return pairs


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


def _should_pair_by_record_order(
    before: CsvTable,
    after: CsvTable,
    before_keyed: list[tuple[tuple[str | None, int], dict[str, str | None]]],
    after_keyed: list[tuple[tuple[str | None, int], dict[str, str | None]]],
) -> bool:
    if len(before.rows) != len(after.rows):
        return False
    if not before.rows or not after.rows:
        return False
    if not before.headers or not after.headers:
        return True
    if before.headers[0] != after.headers[0]:
        return True
    return [key for key, _row in before_keyed] != [key for key, _row in after_keyed]


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
