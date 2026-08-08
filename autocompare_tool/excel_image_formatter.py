from __future__ import annotations

import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from .excel_format_presets import (
    FontSizeExclusionRule,
    normalize_font_size,
    parse_exclusion_rules,
)

Logger = Callable[[str], None]
SUPPORTED_EXTENSIONS = {".xls", ".xlsb", ".xlsm", ".xlsx"}
MACRO_EXTENSIONS = {".xls", ".xlsb", ".xlsm"}
OUTPUT_FOLDER_NAME = "Formatted"
EXCLUDED_SHEET_MARKERS = (
    "変更履歴",
    "サンプル",
    "•ÏX—š—ð",
    "ƒTƒ“ƒvƒ‹",
)
COM_BUSY_HRESULTS = {
    -2147418111,  # RPC_E_CALL_REJECTED
    -2147417846,  # RPC_E_SERVERCALL_RETRYLATER
    -2146777998,  # Excel 0x800AC472 (temporarily busy)
}
COM_RETRY_COUNT = 12
COM_RETRY_DELAY_SECONDS = 0.25


@dataclass
class ExcelImageFormatSummary:
    action_name: str
    root_path: Path
    output_root: Path | None
    file_count: int = 0
    processed_count: int = 0
    sheet_count: int = 0
    shape_count: int = 0
    skipped_sheet_count: int = 0
    workbook_format_sheet_count: int = 0
    font_size_skipped_row_count: int = 0
    macro_skipped_file_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _WorkbookFormatCounts:
    image_sheet_count: int
    shape_count: int
    skipped_image_sheet_count: int
    workbook_format_sheet_count: int
    font_size_skipped_row_count: int


def format_excel_images(
    root_path: str | Path,
    *,
    overwrite_original: bool = False,
    recursive: bool = True,
    draw_format: bool = True,
    run_image_format: bool = True,
    font_name: str = "Meiryo UI",
    font_size: object = 11,
    font_size_exclusions: str | list[object] | None = None,
    log: Logger | None = None,
) -> ExcelImageFormatSummary:
    """Run the workbook's ``FixForMatUTR`` VBA routine for every eligible sheet.

    The source VBA contains dialog-driven button handlers. Calling the underlying
    routine directly is equivalent to choosing "all sheets" without leaving a
    hidden Excel instance waiting for the button dialog.
    """

    logger = log or (lambda _message: None)
    normalized_font_name = str(font_name).strip()
    if not normalized_font_name:
        raise ValueError("Vui lòng nhập tên font chữ.")
    normalized_font_size = normalize_font_size(font_size)
    exclusion_rules = parse_exclusion_rules(font_size_exclusions)
    root = Path(root_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Folder không tồn tại: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Đường dẫn phải là folder: {root}")

    output_root = None if overwrite_original else root / OUTPUT_FOLDER_NAME
    workbooks = _discover_workbooks(root, recursive=recursive, output_root=output_root)
    if not workbooks:
        extensions = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Không tìm thấy workbook Excel ({extensions}) trong folder đã chọn.")

    summary = ExcelImageFormatSummary(
        action_name="Format ảnh Excel",
        root_path=root,
        output_root=output_root,
        file_count=len(workbooks),
    )
    mode = "ghi đè file gốc" if overwrite_original else f"xuất bản sao vào {output_root}"
    logger(f"Tìm thấy {len(workbooks)} workbook; chế độ {mode}.")
    logger(
        f"Định dạng workbook: font {normalized_font_name}, size {normalized_font_size:g}, "
        f"{len(exclusion_rules)} quy tắc loại trừ cỡ chữ."
    )

    with _excel_application() as excel:
        for index, source_path in enumerate(workbooks, start=1):
            if overwrite_original:
                destination = source_path
            else:
                assert output_root is not None
                destination = output_root / source_path.relative_to(root)
            logger(f"[{index}/{len(workbooks)}] Đang format: {source_path}")
            workbook = None
            try:
                if not overwrite_original:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_path, destination)

                workbook = _retry_com_call(
                    lambda: excel.Workbooks.Open(
                        Filename=str(destination),
                        UpdateLinks=0,
                        ReadOnly=False,
                        IgnoreReadOnlyRecommended=True,
                        AddToMru=False,
                    )
                )
                macro_enabled = destination.suffix.lower() in MACRO_EXTENSIONS
                if run_image_format and not macro_enabled:
                    summary.macro_skipped_file_count += 1
                    logger(f"Bỏ qua macro căn ảnh cho {destination.name}: định dạng file không chứa VBA.")
                counts = _format_workbook(
                    excel,
                    workbook,
                    draw_format=draw_format,
                    run_image_format=run_image_format and macro_enabled,
                    font_name=normalized_font_name,
                    font_size=normalized_font_size,
                    exclusion_rules=exclusion_rules,
                    logger=logger,
                )
                _retry_com_call(workbook.Save)
                _retry_com_call(lambda: workbook.Close(SaveChanges=False))
                workbook = None

                summary.processed_count += 1
                summary.sheet_count += counts.image_sheet_count
                summary.shape_count += counts.shape_count
                summary.skipped_sheet_count += counts.skipped_image_sheet_count
                summary.workbook_format_sheet_count += counts.workbook_format_sheet_count
                summary.font_size_skipped_row_count += counts.font_size_skipped_row_count
                logger(
                    f"Hoàn tất {destination.name}: căn ảnh {counts.image_sheet_count} sheet, "
                    f"format font/view {counts.workbook_format_sheet_count} sheet, "
                    f"bỏ qua size tại {counts.font_size_skipped_row_count} row."
                )
            except Exception as exc:  # COM errors vary by installed Excel version.
                if workbook is not None:
                    try:
                        _retry_com_call(lambda: workbook.Close(SaveChanges=False))
                    except Exception:
                        pass
                message = f"{source_path}: {exc}"
                summary.errors.append(message)
                summary.error_count += 1
                logger(f"LỖI: {message}")

    logger(
        f"Đã format {summary.processed_count}/{summary.file_count} workbook, "
        f"{summary.workbook_format_sheet_count} sheet; lỗi {summary.error_count}."
    )
    return summary


def _discover_workbooks(
    root: Path,
    *,
    recursive: bool,
    output_root: Path | None,
) -> list[Path]:
    candidates = root.rglob("*") if recursive else root.iterdir()
    result: list[Path] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.name.startswith("~$") or candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if output_root is not None and _is_relative_to(candidate, output_root):
            continue
        result.append(candidate)
    return sorted(result, key=lambda item: str(item).casefold())


def _format_workbook(
    excel: Any,
    workbook: Any,
    *,
    draw_format: bool,
    run_image_format: bool,
    font_name: str,
    font_size: float,
    exclusion_rules: list[FontSizeExclusionRule],
    logger: Logger,
) -> _WorkbookFormatCounts:
    processed_sheets = 0
    shape_count = 0
    skipped_sheets = 0
    workbook_format_sheets = 0
    skipped_size_rows = 0
    workbook_name = str(_retry_com_call(lambda: workbook.Name)).replace("'", "''")
    macro_name = f"'{workbook_name}'!FixForMatUTR"

    sheet_total = int(_retry_com_call(lambda: workbook.Worksheets.Count))
    for sheet_index in range(1, sheet_total + 1):
        sheet = _retry_com_call(lambda: workbook.Worksheets.Item(sheet_index))
        sheet_name = str(_retry_com_call(lambda: sheet.Name))
        _retry_com_call(sheet.Activate)
        if run_image_format:
            if any(marker in sheet_name for marker in EXCLUDED_SHEET_MARKERS):
                skipped_sheets += 1
                logger(f"Bỏ qua căn ảnh trên sheet đặc biệt: {sheet_name}")
            else:
                shape_count += int(_retry_com_call(lambda: sheet.Shapes.Count))
                _retry_com_call(lambda: excel.Run(macro_name, bool(draw_format)))
                processed_sheets += 1

        skipped_size_rows += _retry_com_call(
            lambda: _apply_sheet_format(
                sheet,
                font_name=font_name,
                font_size=font_size,
                exclusion_rules=exclusion_rules,
            )
        )
        workbook_format_sheets += 1
        _retry_com_call(lambda: _reset_sheet_view(excel, sheet))

    if sheet_total > 0:
        first_sheet = _retry_com_call(lambda: workbook.Worksheets.Item(1))
        _retry_com_call(first_sheet.Activate)
        _retry_com_call(lambda: _reset_sheet_view(excel, first_sheet))

    return _WorkbookFormatCounts(
        image_sheet_count=processed_sheets,
        shape_count=shape_count,
        skipped_image_sheet_count=skipped_sheets,
        workbook_format_sheet_count=workbook_format_sheets,
        font_size_skipped_row_count=skipped_size_rows,
    )


def _apply_sheet_format(
    sheet: Any,
    *,
    font_name: str,
    font_size: float,
    exclusion_rules: list[FontSizeExclusionRule],
) -> int:
    used_range = sheet.UsedRange
    used_range.Font.Name = font_name
    excluded_rows = _excluded_rows(sheet, used_range, exclusion_rules)
    first_row = int(used_range.Row)
    last_row = first_row + int(used_range.Rows.Count) - 1
    first_column = int(used_range.Column)
    last_column = first_column + int(used_range.Columns.Count) - 1
    excluded_in_range = {row for row in excluded_rows if first_row <= row <= last_row}

    if not excluded_in_range:
        used_range.Font.Size = font_size
        return 0

    for start_row, end_row in _included_row_segments(first_row, last_row, excluded_in_range):
        start_cell = sheet.Cells.Item(start_row, first_column)
        end_cell = sheet.Cells.Item(end_row, last_column)
        sheet.Range(start_cell, end_cell).Font.Size = font_size
    return len(excluded_in_range)


def _excluded_rows(
    sheet: Any,
    used_range: Any,
    rules: list[FontSizeExclusionRule],
) -> set[int]:
    rows: set[int] = set()
    for rule in rules:
        if rule.cell_address:
            cell = sheet.Range(rule.cell_address)
            if _values_match(cell.Value2, rule.text):
                rows.add(int(cell.Row))
        else:
            rows.update(_find_matching_rows(used_range, rule.text))
    return rows


def _find_matching_rows(used_range: Any, text: str) -> set[int]:
    rows: set[int] = set()
    escaped_text = text.replace("~", "~~").replace("*", "~*").replace("?", "~?")
    after = used_range.Cells.Item(int(used_range.Cells.Count))
    found = used_range.Find(
        What=escaped_text,
        After=after,
        LookIn=-4163,  # xlValues
        LookAt=1,  # xlWhole
        SearchOrder=1,  # xlByRows
        SearchDirection=1,  # xlNext
        MatchCase=False,
        SearchFormat=False,
    )
    if found is None:
        return rows

    first_address = str(found.Address)
    max_matches = max(int(used_range.Cells.Count), 1)
    for _index in range(max_matches):
        rows.add(int(found.Row))
        found = used_range.FindNext(After=found)
        if found is None or str(found.Address) == first_address:
            break
    return rows


def _values_match(cell_value: Any, expected: str) -> bool:
    if cell_value is None:
        return False
    return str(cell_value).strip().casefold() == expected.strip().casefold()


def _included_row_segments(
    first_row: int,
    last_row: int,
    excluded_rows: set[int],
) -> list[tuple[int, int]]:
    segments: list[tuple[int, int]] = []
    current = first_row
    for excluded_row in sorted(row for row in excluded_rows if first_row <= row <= last_row):
        if current < excluded_row:
            segments.append((current, excluded_row - 1))
        current = excluded_row + 1
    if current <= last_row:
        segments.append((current, last_row))
    return segments


def _reset_sheet_view(excel: Any, sheet: Any) -> None:
    sheet.Activate()
    sheet.Range("A1").Select()
    if excel.ActiveWindow is not None:
        excel.ActiveWindow.ScrollRow = 1
        excel.ActiveWindow.ScrollColumn = 1


def _retry_com_call(operation: Callable[[], Any]) -> Any:
    for attempt in range(COM_RETRY_COUNT):
        try:
            return operation()
        except Exception as exc:
            if not _is_com_busy_error(exc) or attempt == COM_RETRY_COUNT - 1:
                raise
            time.sleep(COM_RETRY_DELAY_SECONDS)
    raise AssertionError("Unreachable COM retry state")


def _is_com_busy_error(exc: Exception) -> bool:
    hresult = getattr(exc, "hresult", None)
    if hresult is None and exc.args:
        hresult = exc.args[0]
    try:
        return int(hresult) in COM_BUSY_HRESULTS
    except (TypeError, ValueError):
        return False


@contextmanager
def _excel_application() -> Iterator[Any]:
    try:
        import pythoncom  # type: ignore[import-not-found]
        from win32com.client import DispatchEx  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Tính năng này cần Microsoft Excel Desktop và package pywin32. "
            "Hãy chạy lại run.bat để cài dependency."
        ) from exc

    pythoncom.CoInitialize()
    excel = None
    try:
        try:
            excel = DispatchEx("Excel.Application")
        except Exception as exc:
            raise RuntimeError(
                "Không thể khởi động Microsoft Excel Desktop. Hãy kiểm tra Excel đã được cài đặt."
            ) from exc
        time.sleep(COM_RETRY_DELAY_SECONDS)
        _retry_com_call(lambda: setattr(excel, "Visible", False))
        _retry_com_call(lambda: setattr(excel, "DisplayAlerts", False))
        _retry_com_call(lambda: setattr(excel, "ScreenUpdating", False))
        _retry_com_call(lambda: setattr(excel, "EnableEvents", False))
        _retry_com_call(lambda: setattr(excel, "AskToUpdateLinks", False))
        yield excel
    finally:
        if excel is not None:
            try:
                _retry_com_call(excel.Quit)
            except Exception:
                pass
        pythoncom.CoUninitialize()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
