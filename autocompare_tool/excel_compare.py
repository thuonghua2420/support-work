from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, PatternFill


Logger = Callable[[str], None]
CancelChecker = Callable[[], None]
SUPPORTED_INPUT_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}
DIFFERENCE_FILL = PatternFill(fill_type="solid", fgColor="FFF2CC")
MAX_SAMPLES_PER_SHEET = 100


@dataclass(frozen=True)
class SheetCompareSummary:
    """Per-sheet outcome shown to the user without opening the output workbook."""

    old_name: str | None
    new_name: str | None
    compare_sheet: str
    pairing: str  # "name", "position", "old_only" or "new_only"
    difference_count: int
    samples: tuple[dict[str, str], ...] = ()
    samples_truncated: bool = False


@dataclass(frozen=True)
class ExcelCompareResult:
    old_path: Path
    new_path: Path
    output_path: Path
    sheet_pair_count: int
    difference_count: int
    missing_old_sheet_count: int
    missing_new_sheet_count: int
    identical: bool = False
    sheets: tuple[SheetCompareSummary, ...] = ()


def compare_excel_workbooks(
    old_path: str | Path,
    new_path: str | Path,
    output_path: str | Path,
    *,
    pair_by_position: bool = True,
    log: Logger | None = None,
    cancel: CancelChecker | None = None,
) -> ExcelCompareResult:
    """Compare two OOXML workbooks cell-by-cell and write source/compare triplets.

    A formula cell differs when its formula text differs, or when both files carry a
    cached result and those results differ. Sheets whose names differ are paired by tab
    order only when ``pair_by_position`` is true; otherwise they are reported as
    present on one side only.
    """

    logger = log or (lambda _message: None)
    cancel_checker = cancel or (lambda: None)
    old_file = _validate_input_path(old_path, "File Excel cũ")
    new_file = _validate_input_path(new_path, "File Excel mới")
    destination = _validate_output_path(output_path, old_file, new_file)

    logger(f"Đang đọc file cũ: {old_file.name}")
    old_book = _SourceWorkbook(old_file)
    try:
        logger(f"Đang đọc file mới: {new_file.name}")
        new_book = _SourceWorkbook(new_file)
        try:
            output_workbook = Workbook()
            output_workbook.remove(output_workbook.active)
            used_names: set[str] = set()
            difference_count = 0
            missing_old_count = 0
            missing_new_count = 0
            summaries: list[SheetCompareSummary] = []

            sheet_pairs = _pair_worksheets(old_book.formulas, new_book.formulas, pair_by_position)

            for index, (old_sheet, new_sheet) in enumerate(sheet_pairs, start=1):
                cancel_checker()
                missing_old_count += old_sheet is None
                missing_new_count += new_sheet is None
                pair_name = new_sheet.title if new_sheet is not None else old_sheet.title
                old_name = old_sheet.title if old_sheet is not None else pair_name
                new_name = new_sheet.title if new_sheet is not None else pair_name

                old_output = output_workbook.create_sheet(_sheet_name_with_suffix(old_name, "_Old", used_names))
                new_output = output_workbook.create_sheet(_sheet_name_with_suffix(new_name, "_New", used_names))
                compare_output = output_workbook.create_sheet(_sheet_name_with_suffix(pair_name, "_compare", used_names))

                if old_sheet is not None:
                    _copy_worksheet(old_sheet, old_output, cancel_checker)
                if new_sheet is not None:
                    _copy_worksheet(new_sheet, new_output, cancel_checker)

                differences, samples, truncated = _write_compare_sheet(
                    old_sheet,
                    new_sheet,
                    old_book.cached(old_sheet),
                    new_book.cached(new_sheet),
                    compare_output,
                    cancel_checker,
                )
                difference_count += differences
                pairing = (
                    "old_only" if new_sheet is None
                    else "new_only" if old_sheet is None
                    else "name" if old_name == new_name
                    else "position"
                )
                summaries.append(SheetCompareSummary(
                    old_name=old_sheet.title if old_sheet is not None else None,
                    new_name=new_sheet.title if new_sheet is not None else None,
                    compare_sheet=compare_output.title,
                    pairing=pairing,
                    difference_count=differences,
                    samples=tuple(samples),
                    samples_truncated=truncated,
                ))
                pair_label = pair_name if old_name == new_name else f"{old_name} ⇄ {new_name}"
                logger(
                    f"[{index}/{len(sheet_pairs)}] Sheet {pair_label}: "
                    f"{differences} ô sai khác."
                )

            if output_workbook.worksheets:
                output_workbook.active = 2 if len(output_workbook.worksheets) >= 3 else 0
            destination.parent.mkdir(parents=True, exist_ok=True)
            cancel_checker()
            try:
                output_workbook.save(destination)
            except PermissionError as exc:
                raise PermissionError(
                    f"Không ghi được file kết quả: {destination}. "
                    "Hãy đóng file nếu đang mở trong Excel hoặc chọn tên file khác."
                ) from exc
            output_workbook.close()
        finally:
            new_book.close()
    finally:
        old_book.close()

    logger(f"Đã tạo file compare Excel: {destination}")
    return ExcelCompareResult(
        old_path=old_file,
        new_path=new_file,
        output_path=destination,
        sheet_pair_count=len(sheet_pairs),
        difference_count=difference_count,
        missing_old_sheet_count=missing_old_count,
        missing_new_sheet_count=missing_new_count,
        identical=difference_count == 0 and not missing_old_count and not missing_new_count,
        sheets=tuple(summaries),
    )


class _SourceWorkbook:
    """A workbook loaded twice: formulas for display/copy and cached results for comparison."""

    def __init__(self, path: Path) -> None:
        self.formulas = load_workbook(path, data_only=False, rich_text=True)
        try:
            self.values = load_workbook(path, data_only=True, rich_text=True)
        except Exception:
            self.formulas.close()
            raise

    def cached(self, sheet: Any | None) -> Any | None:
        if sheet is None:
            return None
        return self.values.worksheets[self.formulas.worksheets.index(sheet)]

    def close(self) -> None:
        self.formulas.close()
        self.values.close()


def _validate_input_path(path_value: str | Path, label: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} không tồn tại: {path}")
    if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
        raise ValueError(f"{label} phải là file XLSX/XLSM/XLTX/XLTM.")
    return path


def _validate_output_path(path_value: str | Path, old_path: Path, new_path: Path) -> Path:
    path = Path(path_value).expanduser()
    if not str(path).strip():
        raise ValueError("Vui lòng chọn file Excel kết quả.")
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    path = path.resolve()
    if path == old_path or path == new_path:
        raise ValueError("File kết quả phải khác hai file Excel nguồn.")
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


def _unique_sheet_name(requested_name: str, used_names: set[str]) -> str:
    invalid = set('[]:*?/\\')
    clean = "".join("_" if character in invalid else character for character in requested_name).strip("'")
    clean = clean or "Sheet"
    candidate = clean[:31]
    index = 2
    while candidate.casefold() in used_names:
        suffix = f"_{index}"
        candidate = f"{clean[: 31 - len(suffix)]}{suffix}"
        index += 1
    used_names.add(candidate.casefold())
    return candidate


def _sheet_name_with_suffix(base_name: str, suffix: str, used_names: set[str]) -> str:
    clean_base = "".join("_" if character in set('[]:*?/\\') else character for character in base_name).strip("'")
    clean_base = clean_base or "Sheet"
    requested = f"{clean_base[: 31 - len(suffix)]}{suffix}"
    return _unique_sheet_name(requested, used_names)


def _copy_worksheet(source: Any, target: Any, cancel: CancelChecker) -> None:
    target.sheet_format = copy(source.sheet_format)
    target.sheet_properties = copy(source.sheet_properties)
    target.page_margins = copy(source.page_margins)
    target.page_setup = copy(source.page_setup)
    target.print_options = copy(source.print_options)
    target.freeze_panes = source.freeze_panes
    target.sheet_view.showGridLines = source.sheet_view.showGridLines
    target.sheet_state = source.sheet_state
    target.auto_filter.ref = source.auto_filter.ref

    for key, dimension in source.column_dimensions.items():
        target.column_dimensions[key] = copy(dimension)
    for key, dimension in source.row_dimensions.items():
        target.row_dimensions[key] = copy(dimension)

    for row_number, row in enumerate(source.iter_rows(), start=1):
        if row_number % 250 == 0:
            cancel()
        for source_cell in row:
            if isinstance(source_cell, MergedCell):
                continue
            target_cell = target.cell(source_cell.row, source_cell.column, source_cell.value)
            if source_cell.has_style:
                target_cell._style = copy(source_cell._style)
            if source_cell.number_format:
                target_cell.number_format = source_cell.number_format
            if source_cell.hyperlink:
                target_cell._hyperlink = copy(source_cell.hyperlink)
            if source_cell.comment:
                target_cell.comment = copy(source_cell.comment)

    for merged_range in source.merged_cells.ranges:
        target.merge_cells(str(merged_range))


def _write_compare_sheet(
    old_sheet: Any | None,
    new_sheet: Any | None,
    old_cached: Any | None,
    new_cached: Any | None,
    target: Any,
    cancel: CancelChecker,
) -> tuple[int, list[dict[str, str]], bool]:
    reference = new_sheet or old_sheet
    if reference is not None:
        target.sheet_view.showGridLines = reference.sheet_view.showGridLines
        target.freeze_panes = reference.freeze_panes
        for key, dimension in reference.column_dimensions.items():
            target.column_dimensions[key] = copy(dimension)
        for key, dimension in reference.row_dimensions.items():
            target.row_dimensions[key] = copy(dimension)

    max_row = max(old_sheet.max_row if old_sheet is not None else 0, new_sheet.max_row if new_sheet is not None else 0)
    max_column = max(old_sheet.max_column if old_sheet is not None else 0, new_sheet.max_column if new_sheet is not None else 0)
    difference_count = 0
    samples: list[dict[str, str]] = []

    for row in range(1, max_row + 1):
        if row % 250 == 0:
            cancel()
        for column in range(1, max_column + 1):
            old_state = _cell_state(old_sheet, old_cached, row, column)
            new_state = _cell_state(new_sheet, new_cached, row, column)
            if _states_equal(old_state, new_state):
                continue
            old_text, new_text = _display_pair(old_state, new_state)
            target_cell = target.cell(row, column)
            target_cell.value = _difference_text(old_text, new_text)
            target_cell.fill = copy(DIFFERENCE_FILL)
            target_cell.alignment = Alignment(vertical="top", wrap_text=True)
            difference_count += 1
            if len(samples) < MAX_SAMPLES_PER_SHEET:
                samples.append({"cell": target_cell.coordinate, "old": old_text, "new": new_text})

    return difference_count, samples, difference_count > len(samples)


@dataclass(frozen=True)
class _CellState:
    kind: str  # "blank", "formula", "text", "number", "bool", "date" or "error"
    content: Any = None
    cached: Any = None  # cached formula result; None when the file stores none


def _cell_state(sheet: Any | None, cached_sheet: Any | None, row: int, column: int) -> _CellState:
    if sheet is None:
        return _CellState("blank")
    cell = sheet.cell(row, column)
    value = cell.value
    if value is None:
        return _CellState("blank")
    if isinstance(value, CellRichText):
        return _CellState("text", str(value))
    if cell.data_type == "f":
        cached = cached_sheet.cell(row, column).value if cached_sheet is not None else None
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


def _difference_text(old_text: str, new_text: str) -> CellRichText:
    bold = InlineFont(b=True)
    return CellRichText(
        [
            TextBlock(bold, "Old:"),
            old_text,
            " # ",
            TextBlock(bold, "New:"),
            new_text,
        ]
    )


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
