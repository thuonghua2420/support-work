from __future__ import annotations

from dataclasses import dataclass

from .csv_table import CsvTable
from .compare_diagnostics import CompareDiagnosticError, csv_location

STATUS_INSERT = "INSERT"
STATUS_DELETE = "DELETE"
STATUS_UPDATE = "UPDATE"
STATUS_UNCHANGED = "UNCHANGED"

SKIP_COLUMN_NAMES = {"ValidationErrors", "HasErrors", "TargetProperties", "DataState"}


@dataclass(frozen=True)
class RecordPair:
    before: dict[str, str | None] | None
    after: dict[str, str | None] | None
    before_index: int | None = None
    after_index: int | None = None
    status: str = ""


@dataclass(frozen=True)
class SheetComparison:
    name: str
    before_headers: list[str]
    after_headers: list[str]
    columns: list[str]
    pairs: list[RecordPair]
    match_mode: str = "position"
    fallback_reason: str = ""

    def status_counts(self) -> dict[str, int]:
        counts = dict.fromkeys((STATUS_INSERT, STATUS_DELETE, STATUS_UPDATE, STATUS_UNCHANGED), 0)
        for pair in self.pairs:
            counts[pair.status or _record_status(pair.before, pair.after, self.columns)] += 1
        return counts


def build_sheet_comparison(
    name: str, before: CsvTable, after: CsvTable, *, key_columns: tuple[str, ...] | None = None,
) -> SheetComparison:
    columns = _union_headers(before.headers, after.headers)
    fallback_reason = "Không có key trong [update_compare_keys]."
    if key_columns:
        before_index, reason = _keyed_index(before, key_columns, "Trái")
        after_index, after_reason = _keyed_index(after, key_columns, "Phải")
        fallback_reason = reason or after_reason
        if not fallback_reason:
            return SheetComparison(
                name, before.headers, after.headers, columns,
                _pair_by_key_merge(before, after, before_index, after_index, columns), "key",
            )
    return SheetComparison(
        name, before.headers, after.headers, columns,
        _pair_by_record_order(before.rows, after.rows, columns), fallback_reason=fallback_reason,
    )


def _pair_by_record_order(
    before_rows: list[dict[str, str | None]],
    after_rows: list[dict[str, str | None]],
    columns: list[str],
) -> list[RecordPair]:
    pairs: list[RecordPair] = []
    for index in range(max(len(before_rows), len(after_rows))):
        before_row = before_rows[index] if index < len(before_rows) else None
        after_row = after_rows[index] if index < len(after_rows) else None
        pairs.append(RecordPair(
            before_row, after_row, index if before_row is not None else None,
            index if after_row is not None else None, _record_status(before_row, after_row, columns),
        ))
    return pairs


def _record_status(
    before: dict[str, str | None] | None, after: dict[str, str | None] | None, columns: list[str],
) -> str:
    if before is None:
        return STATUS_INSERT
    if after is None:
        return STATUS_DELETE
    return STATUS_UPDATE if any(not cell_values_equal(before, after, column) for column in columns) else STATUS_UNCHANGED


def _keyed_index(
    table: CsvTable, key_columns: tuple[str, ...], side: str,
) -> tuple[list[tuple[tuple[str, ...], int]], str]:
    # Missing/empty files have no header and need no key validation.
    if not table.headers and not table.rows:
        return [], ""
    names = [name.casefold() for name in table.headers]
    key_names = [name.casefold() for name in key_columns]
    if len(set(names)) != len(names) or len(set(key_names)) != len(key_names):
        return [], f"Phía {side}: Header/key có tên column trùng nhau (không phân biệt hoa/thường)."
    missing = [name for name in key_columns if name.casefold() not in names]
    if missing:
        return [], f"Phía {side}: Không tìm thấy column key trong header CSV: {', '.join(missing)}."
    headers = [table.headers[names.index(name)] for name in key_names]
    indexed: list[tuple[tuple[str, ...], int]] = []
    for index, row in enumerate(table.rows):
        key = tuple(row.get(header) for header in headers)
        if any(value is None or not value.strip() for value in key):
            return [], _key_problem(table, side, index, key, "Key NULL/blank.")
        indexed.append((key, index))
    indexed.sort(key=lambda item: item[0])
    duplicate = min(
        ((previous, current) for previous, current in zip(indexed, indexed[1:]) if previous[0] == current[0]),
        key=lambda pair: pair[1][1], default=None,
    )
    if duplicate is not None:
        previous, current = duplicate
        return [], _key_problem(
            table, side, current[1], current[0], f"Duplicate key; record trùng trước đó: {previous[1] + 1}.",
        )
    return indexed, ""


def _key_problem(table: CsvTable, side: str, index: int, key: tuple, message: str) -> str:
    record = index + 1
    lines = table.line_ranges[record] if record < len(table.line_ranges) else None
    return str(CompareDiagnosticError(
        message, **{"Phía": side}, **csv_location(record, lines=lines), **{"Giá trị key": repr(key)},
    ))


def _pair_by_key_merge(
    before: CsvTable, after: CsvTable,
    before_index: list[tuple[tuple[str, ...], int]], after_index: list[tuple[tuple[str, ...], int]],
    columns: list[str],
) -> list[RecordPair]:
    pairs: list[RecordPair] = []
    left = right = 0
    while left < len(before_index) or right < len(after_index):
        left_key = before_index[left][0] if left < len(before_index) else None
        right_key = after_index[right][0] if right < len(after_index) else None
        before_source = after_source = None
        if left_key is not None and (right_key is None or left_key <= right_key):
            before_source = before_index[left][1]
            left += 1
        if right_key is not None and (left_key is None or right_key <= left_key):
            after_source = after_index[right][1]
            right += 1
        before_row = before.rows[before_source] if before_source is not None else None
        after_row = after.rows[after_source] if after_source is not None else None
        pairs.append(RecordPair(
            before_row, after_row, before_source, after_source, _record_status(before_row, after_row, columns),
        ))
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
