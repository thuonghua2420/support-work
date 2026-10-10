"""Record totals embedded in, and read from, generated Compare workbooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

METADATA_PREFIX = "AUTOCOMPARE_RECORD_COUNTS_V1:"


def store_record_counts(workbook: Any, counts: Mapping[str, tuple[int, int]]) -> None:
    """Keep source row totals in workbook properties without adding visible cells."""
    payload = {name: [left, right] for name, (left, right) in counts.items()}
    workbook.properties.description = METADATA_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def read_record_counts(workbook_path: Path) -> list[dict[str, Any]]:
    """Return both sides' totals for every visible comparison sheet."""
    from openpyxl import load_workbook

    workbook = load_workbook(workbook_path, read_only=True, data_only=False)
    try:
        stored = _stored_counts(workbook.properties.description)
        rows: list[dict[str, Any]] = []
        for sheet in workbook.worksheets:
            if getattr(sheet, "sheet_state", "visible") != "visible":
                continue
            if sheet.title in stored:
                left_count, right_count = stored[sheet.title]
                approximate = False
            else:
                left_count, right_count = _infer_counts(sheet)
                approximate = True
            rows.append({
                "sheet_name": sheet.title,
                "left_count": left_count,
                "right_count": right_count,
                "difference": right_count - left_count,
                "matches": left_count == right_count,
                "approximate": approximate,
            })
        return rows
    finally:
        workbook.close()


def _stored_counts(description: str | None) -> dict[str, tuple[int, int]]:
    if not description or not description.startswith(METADATA_PREFIX):
        return {}
    try:
        raw = json.loads(description[len(METADATA_PREFIX):])
    except (ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, tuple[int, int]] = {}
    for name, pair in raw.items():
        if (isinstance(name, str) and isinstance(pair, list) and len(pair) == 2
                and all(type(value) is int and value >= 0 for value in pair)):
            counts[name] = (pair[0], pair[1])
    return counts


def _infer_counts(sheet: Any) -> tuple[int, int]:
    """Best effort for older workbooks that did not record source totals."""
    header = next(sheet.iter_rows(min_row=2, max_row=2, values_only=True), ())
    pair_starts: list[int] = []
    column = 2  # zero-based C
    while column + 1 < len(header) and header[column] is not None and header[column + 1] is not None:
        pair_starts.append(column)
        column += 2
    if not pair_starts:
        return 0, 0

    left_seen = [False] * len(pair_starts)
    right_seen = [False] * len(pair_starts)
    for row in sheet.iter_rows(min_row=3, values_only=True):
        for index, pair_start in enumerate(pair_starts):
            if len(row) > pair_start and row[0] not in (None, "") and row[pair_start] not in (None, ""):
                left_seen[index] = True
            if len(row) > pair_start + 1 and row[1] not in (None, "") and row[pair_start + 1] not in (None, ""):
                right_seen[index] = True
    # A pair where both sides display only blank cells is ambiguous. Count it
    # on both sides so a genuinely blank record is retained in the estimate.
    left_count = sum(left or not right for left, right in zip(left_seen, right_seen))
    right_count = sum(right or not left for left, right in zip(left_seen, right_seen))
    return left_count, right_count
