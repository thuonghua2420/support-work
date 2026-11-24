from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, closing
from dataclasses import dataclass
from datetime import date, datetime, time
from itertools import zip_longest
from pathlib import Path
from typing import Any, Callable

from openpyxl import load_workbook
from openpyxl.cell.read_only import EMPTY_CELL
from openpyxl.cell.rich_text import CellRichText
from openpyxl.utils import get_column_letter

from .app_config import DEFAULT_EXCEL_COMPARE_MAX_DETAIL_ROWS
from .excel_compare_store import CHANGE_TYPES, MAX_EXCEL_COLUMNS, DiffRow, ExcelCompareStore, default_store


Logger = Callable[[str], None]
CancelChecker = Callable[[], None]
SUPPORTED_INPUT_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}
_DETAIL_BATCH_SIZE = 1000


@dataclass(frozen=True)
class SheetCompareSummary:
    index: int
    old_name: str | None
    new_name: str | None
    pairing: str  # "name", "position", "old_only" or "new_only"
    difference_count: int
    counts_by_type: dict[str, int]
    old_rows: int
    old_columns: int
    new_rows: int
    new_columns: int
    top_columns: tuple[dict[str, str | int], ...]
    details_truncated: bool


@dataclass(frozen=True)
class ExcelCompareResult:
    old_path: Path
    new_path: Path
    report_id: str
    sheet_pair_count: int
    difference_count: int
    missing_old_sheet_count: int
    missing_new_sheet_count: int
    identical: bool
    details_truncated: bool
    sheets: tuple[SheetCompareSummary, ...]


def compare_excel_workbooks(
    old_path: str | Path,
    new_path: str | Path,
    *,
    pair_by_position: bool = True,
    log: Logger | None = None,
    cancel: CancelChecker | None = None,
    store: ExcelCompareStore | None = None,
    max_detail_rows: int | None = None,
) -> ExcelCompareResult:
    """Compare cells by position and spool a bounded number of differences to disk."""
    logger = log or (lambda _message: None)
    cancel_checker = cancel or (lambda: None)
    old_file = _validate_input_path(old_path, "File Excel cũ")
    new_file = _validate_input_path(new_path, "File Excel mới")
    store = default_store if store is None else store
    remaining = DEFAULT_EXCEL_COMPARE_MAX_DETAIL_ROWS if max_detail_rows is None else max(0, max_detail_rows)

    cancel_checker()
    report_id = store.create()
    try:
        summaries: list[SheetCompareSummary] = []
        with ExitStack() as resources:
            logger(f"Đang đọc file cũ: {old_file.name}")
            old_formulas, old_cached = _open_source(old_file, resources)
            cancel_checker()
            logger(f"Đang đọc file mới: {new_file.name}")
            new_formulas, new_cached = _open_source(new_file, resources)
            old_values = dict(zip(old_formulas.worksheets, old_cached.worksheets, strict=True))
            new_values = dict(zip(new_formulas.worksheets, new_cached.worksheets, strict=True))
            sheet_pairs = _pair_worksheets(old_formulas, new_formulas, pair_by_position)

            for index, (old_sheet, new_sheet) in enumerate(sheet_pairs):
                cancel_checker()
                old_name = old_sheet.title if old_sheet is not None else None
                new_name = new_sheet.title if new_sheet is not None else None
                label = new_name or old_name
                if old_name and new_name and old_name != new_name:
                    label = f"{old_name} ⇄ {new_name}"
                progress = f"[{index + 1}/{len(sheet_pairs)}] Sheet {label}"
                logger(f"{progress}: đang so sánh...")
                summary, stored = _compare_sheet(
                    index, old_sheet, new_sheet, old_values.get(old_sheet), new_values.get(new_sheet),
                    store, report_id, remaining, progress, logger, cancel_checker,
                )
                summaries.append(summary)
                remaining -= stored
                logger(f"{progress}: {summary.difference_count} ô sai khác.")

        cancel_checker()
        difference_count = sum(sheet.difference_count for sheet in summaries)
        missing_old_count = sum(sheet.old_name is None for sheet in summaries)
        missing_new_count = sum(sheet.new_name is None for sheet in summaries)
        result = ExcelCompareResult(
            old_path=old_file,
            new_path=new_file,
            report_id=report_id,
            sheet_pair_count=len(summaries),
            difference_count=difference_count,
            missing_old_sheet_count=missing_old_count,
            missing_new_sheet_count=missing_new_count,
            identical=not (difference_count or missing_old_count or missing_new_count),
            details_truncated=any(sheet.details_truncated for sheet in summaries),
            sheets=tuple(summaries),
        )
        store.finish(result)
    except BaseException:
        store.delete(report_id)
        raise
    return result


def _open_source(path: Path, resources: ExitStack) -> tuple[Any, Any]:
    books = []
    for data_only in (False, True):
        source = resources.enter_context(path.open("rb"))
        book = load_workbook(source, read_only=True, rich_text=True, data_only=data_only, keep_links=False)
        resources.callback(book.close)
        books.append(book)
    return books[0], books[1]


def _validate_input_path(path_value: str | Path, label: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} không tồn tại: {path}")
    if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError(f"{label} phải là file XLSX/XLSM/XLTX/XLTM.")
    return path


def _pair_worksheets(
    old_workbook: Any, new_workbook: Any, pair_by_position: bool = True
) -> list[tuple[Any | None, Any | None]]:
    old_sheets = list(old_workbook.worksheets)
    new_sheets = list(new_workbook.worksheets)
    new_by_name = {sheet.title: index for index, sheet in enumerate(new_sheets)}
    reserved_exact = {new_by_name[sheet.title] for sheet in old_sheets if sheet.title in new_by_name}
    used_new: set[int] = set()
    pairs: list[tuple[Any | None, Any | None]] = []

    for old_sheet in old_sheets:
        exact_index = new_by_name.get(old_sheet.title)
        if exact_index is not None and exact_index not in used_new:
            new_index = exact_index
        elif pair_by_position:
            new_index = next(
                (
                    index
                    for index in range(len(new_sheets))
                    if index not in used_new and index not in reserved_exact
                ),
                None,
            )
        else:
            new_index = None
        new_sheet = new_sheets[new_index] if new_index is not None else None
        if new_index is not None:
            used_new.add(new_index)
        pairs.append((old_sheet, new_sheet))

    pairs.extend((None, sheet) for index, sheet in enumerate(new_sheets) if index not in used_new)
    return pairs


def _sheet_rows(sheet: Any | None) -> Iterator[tuple]:
    if sheet is not None:
        sheet.reset_dimensions()
        yield from sheet.iter_rows()


def _row_key(row: tuple) -> tuple:
    # Excel kinds matter even when Python's native values compare equal (e.g. True and 1).
    return tuple((cell.value, cell.data_type) for cell in row)


def _row_headers(old: tuple, new: tuple) -> tuple[str, ...]:
    return tuple(
        _state_text(_cell_state(new_cell)) or _state_text(_cell_state(old_cell))
        for old_cell, new_cell in zip_longest(
            old[:MAX_EXCEL_COLUMNS], new[:MAX_EXCEL_COLUMNS], fillvalue=EMPTY_CELL
        )
    )


def _compare_sheet(
    index: int,
    old_sheet: Any | None,
    new_sheet: Any | None,
    old_cached: Any | None,
    new_cached: Any | None,
    store: ExcelCompareStore,
    report_id: str,
    remaining: int,
    progress: str,
    log: Logger,
    cancel: CancelChecker,
) -> tuple[SheetCompareSummary, int]:
    old_name = old_sheet.title if old_sheet is not None else None
    new_name = new_sheet.title if new_sheet is not None else None
    pairing = (
        "old_only" if new_sheet is None
        else "new_only" if old_sheet is None
        else "name" if old_name == new_name
        else "position"
    )
    old_rows = new_rows = old_columns = new_columns = 0
    headers: tuple[str, ...] = ()
    counts = dict.fromkeys(CHANGE_TYPES, 0)
    columns: Counter[int] = Counter()
    batch: list[DiffRow] = []
    stored = 0

    with ExitStack() as streams:
        rows = [
            streams.enter_context(closing(_sheet_rows(sheet)))
            for sheet in (old_sheet, new_sheet, old_cached, new_cached)
        ]
        for row, (old, new, cached_old, cached_new) in enumerate(zip_longest(*rows), start=1):
            if row % 250 == 0:
                cancel()
            if row % 50_000 == 0:
                log(f"{progress}: đã duyệt {row:,} hàng...")
            if old is not None:
                old_rows = row
                old_columns = max(old_columns, len(old))
            if new is not None:
                new_rows = row
                new_columns = max(new_columns, len(new))
            old, new = old or (), new or ()
            cached_old, cached_new = cached_old or (), cached_new or ()
            if row == 1:
                headers = _row_headers(old, new)

            old_key = _row_key(old)
            new_key = _row_key(new)
            if old_key == new_key and (
                all(data_type != "f" for _, data_type in old_key)
                or _row_key(cached_old) == _row_key(cached_new)
            ):
                continue

            for col, (old_cell, new_cell, old_value, new_value) in enumerate(
                zip_longest(old, new, cached_old, cached_new, fillvalue=EMPTY_CELL), start=1
            ):
                old_state = _cell_state(old_cell, old_value)
                new_state = _cell_state(new_cell, new_value)
                if _states_equal(old_state, new_state):
                    continue
                change_type = _classify_change(old_state, new_state)
                counts[change_type] += 1
                columns[col] += 1
                if stored < remaining:
                    column = get_column_letter(col)
                    header = headers[col - 1] if col <= len(headers) else ""
                    old_text, new_text = _display_pair(old_state, new_state)
                    batch.append((index, row, col, f"{column}{row}", change_type, header, old_text, new_text))
                    stored += 1
                    if len(batch) == _DETAIL_BATCH_SIZE:
                        store.add_batch(report_id, batch)
                        batch.clear()
    if batch:
        store.add_batch(report_id, batch)

    difference_count = sum(counts.values())
    top_columns = tuple(
        {"column": get_column_letter(col), "header": headers[col - 1] if col <= len(headers) else "", "count": count}
        for col, count in sorted(columns.items(), key=lambda item: (-item[1], item[0]))[:10]
    )
    return SheetCompareSummary(
        index=index,
        old_name=old_name,
        new_name=new_name,
        pairing=pairing,
        difference_count=difference_count,
        counts_by_type=counts,
        old_rows=old_rows,
        old_columns=old_columns,
        new_rows=new_rows,
        new_columns=new_columns,
        top_columns=top_columns,
        details_truncated=difference_count > stored,
    ), stored


@dataclass(frozen=True)
class _CellState:
    kind: str  # "blank", "formula", "text", "number", "bool", "date" or "error"
    content: Any = None
    cached: Any = None  # cached formula result; None when the file stores none


_BLANK_STATE = _CellState("blank")


def _cell_state(cell: Any, cached_cell: Any = EMPTY_CELL) -> _CellState:
    value = cell.value
    if value is None:
        return _BLANK_STATE
    if isinstance(value, CellRichText):
        return _CellState("text", str(value))
    if cell.data_type == "f":
        cached = cached_cell.value
        if isinstance(cached, CellRichText):
            cached = str(cached)
        return _CellState("formula", _formula_text(value), cached)
    if cell.data_type == "e":
        return _CellState("error", str(value))
    if isinstance(value, bool):
        return _CellState("bool", value)
    if isinstance(value, (int, float)):
        return _CellState("number", value)
    if isinstance(value, (datetime, date, time)):
        return _CellState("date", value)
    return _CellState("text", str(value))


def _formula_text(value: Any) -> str:
    text = getattr(value, "text", None)
    return str(text if text is not None else value)


def _states_equal(old: _CellState, new: _CellState) -> bool:
    if old.kind != new.kind or old.content != new.content:
        return False
    # Cached results are only comparable when both files store one.
    if old.kind == "formula" and old.cached is not None and new.cached is not None:
        return old.cached == new.cached
    return True


def _classify_change(old: _CellState, new: _CellState) -> str:
    if old.kind == "blank":
        return "added"
    if new.kind == "blank":
        return "removed"
    if "formula" in (old.kind, new.kind):
        return "formula"
    if old.kind != new.kind and _state_text(old) == _state_text(new):
        return "kind"
    return "changed"


_KIND_LABELS = {
    "text": "văn bản",
    "number": "số",
    "bool": "TRUE/FALSE",
    "date": "ngày giờ",
    "error": "lỗi",
    "formula": "công thức",
}


def _display_pair(old: _CellState, new: _CellState) -> tuple[str, str]:
    """Render both sides, adding hints when plain text would hide the real difference."""

    old_text = _state_text(old)
    new_text = _state_text(new)
    if old.kind != "blank" and new.kind != "blank":
        if old_text == new_text and old.kind != new.kind:
            old_text = f"{old_text} ({_KIND_LABELS[old.kind]})"
            new_text = f"{new_text} ({_KIND_LABELS[new.kind]})"
        elif (
            _collapse_whitespace(old_text) == _collapse_whitespace(new_text)
            or _edge_whitespace(old_text)
            or _edge_whitespace(new_text)
        ):
            old_text, new_text = f'"{old_text}"', f'"{new_text}"'
    return old_text, new_text


def _state_text(state: _CellState) -> str:
    if state.kind == "blank":
        return ""
    if state.kind == "formula":
        if state.cached is None:
            return str(state.content)
        return f"{state.content} → {_display_value(state.cached)}"
    return _display_value(state.content)


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _edge_whitespace(text: str) -> bool:
    return bool(text) and text != text.strip()


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, CellRichText):
        return str(value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return str(value)
