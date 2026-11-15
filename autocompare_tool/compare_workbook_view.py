from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree

from openpyxl import load_workbook
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import get_column_letter

from .app_config import ExcelCompareStyleConfig, load_app_config
from .excel_writer import WorkbookFixmeEntry
from .compare import STATUS_INSERT, STATUS_DELETE, STATUS_UPDATE, STATUS_UNCHANGED


@dataclass(frozen=True)
class CompareWorkbookReference:
    case_folder_name: str
    workbook_path: Path
    workbook_name: str


@dataclass(frozen=True)
class WorkbookStyleContext:
    theme_colors: tuple[str, ...]
    indexed_colors: tuple[str, ...]


THEME_COLOR_ORDER = (
    "lt1",
    "dk1",
    "lt2",
    "dk2",
    "accent1",
    "accent2",
    "accent3",
    "accent4",
    "accent5",
    "accent6",
    "hlink",
    "folHlink",
)
THEME_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def build_compare_view_index(workbooks: Sequence[CompareWorkbookReference]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    case_lookup: dict[str, dict[str, Any]] = {}

    for workbook_id, reference in enumerate(workbooks):
        if not reference.workbook_path.exists() or not reference.workbook_path.is_file():
            continue
        case_name = reference.case_folder_name or "Compare"
        case_id = _case_id(case_name, len(cases))
        if case_name not in case_lookup:
            case_item = {"id": case_id, "name": case_name, "workbooks": []}
            case_lookup[case_name] = case_item
            cases.append(case_item)
        error = ""
        try:
            sheet_names = _sheet_names(reference.workbook_path)
        except Exception as exc:  # pragma: no cover - defensive for corrupt/locked workbooks.
            sheet_names = []
            error = str(exc)
        case_lookup[case_name]["workbooks"].append(
            {
                "id": str(workbook_id),
                "name": reference.workbook_name,
                "path": str(reference.workbook_path),
                "sheets": [{"name": sheet_name} for sheet_name in sheet_names],
                "error": error,
            }
        )

    return {"cases": cases}


def read_compare_sheet(
    reference: CompareWorkbookReference,
    sheet_name: str,
    fixme_entries: Sequence[WorkbookFixmeEntry],
) -> dict[str, Any]:
    if not reference.workbook_path.exists() or not reference.workbook_path.is_file():
        raise FileNotFoundError(f"File compare không tồn tại: {reference.workbook_path}")

    workbook = load_workbook(reference.workbook_path)
    try:
        if sheet_name not in workbook.sheetnames:
            if not workbook.sheetnames:
                raise ValueError(f"File compare không có sheet: {reference.workbook_path}")
            sheet_name = workbook.sheetnames[0]

        worksheet = workbook[sheet_name]
        style_context = _workbook_style_context(workbook)
        compare_style = load_app_config().excel_compare_style
        max_row = worksheet.max_row or 1
        max_column = worksheet.max_column or 1
        fixme_by_cell = _fixme_indices_by_cell(reference.workbook_path, sheet_name, fixme_entries)
        column_widths = [_column_pixel_width(worksheet, column_index) for column_index in range(1, max_column + 1)]
        record_count_mismatch_pair_starts = _record_count_mismatch_pair_starts(
            worksheet, max_row, max_column
        )

        record_statuses = _record_statuses(worksheet, max_row, max_column, record_count_mismatch_pair_starts)
        status_counts = dict.fromkeys((STATUS_INSERT, STATUS_DELETE, STATUS_UPDATE, STATUS_UNCHANGED), 0)
        for record in record_statuses:
            status_counts[record["status"]] += 1

        rows: list[dict[str, Any]] = []
        for row_index in range(1, max_row + 1):
            cells: list[dict[str, Any]] = []
            for column_index in range(1, max_column + 1):
                cell = worksheet.cell(row_index, column_index)
                cells.append(
                    {
                        "row": row_index,
                        "column": column_index,
                        "coordinate": cell.coordinate,
                        "value": _display_value(cell.value),
                        "style": _cell_style(
                            cell,
                            style_context,
                            worksheet,
                            row_index,
                            column_index,
                            fixme_by_cell,
                            compare_style,
                        ),
                        "fixme_indices": fixme_by_cell.get((row_index, column_index), []),
                    }
                )
            rows.append({"number": row_index, "height": _row_pixel_height(worksheet, row_index), "cells": cells})

        return {
            "case_name": reference.case_folder_name or "Compare",
            "workbook_name": reference.workbook_name,
            "workbook_path": str(reference.workbook_path),
            "sheet_name": sheet_name,
            "row_count": max_row,
            "column_count": max_column,
            "record_statuses": record_statuses,
            "status_counts": status_counts,
            "record_count_mismatch": bool(record_count_mismatch_pair_starts),
            "record_count_mismatch_pair_starts": record_count_mismatch_pair_starts,
            "column_letters": [get_column_letter(index) for index in range(1, max_column + 1)],
            "column_widths": column_widths,
            "rows": rows,
        }
    finally:
        workbook.close()


def scan_compare_workbook_fixmes(workbooks: Sequence[CompareWorkbookReference]) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    for reference in workbooks:
        if not reference.workbook_path.exists() or not reference.workbook_path.is_file():
            continue
        workbook = load_workbook(reference.workbook_path, read_only=True, data_only=False)
        try:
            for worksheet in workbook.worksheets:
                for row in worksheet.iter_rows():
                    for cell in row:
                        value = _display_value(cell.value).strip()
                        if value.upper() != "FIXME":
                            continue
                        locations.append(
                            {
                                "case_folder_name": reference.case_folder_name or "Compare",
                                "workbook_name": reference.workbook_name,
                                "workbook_path": str(reference.workbook_path),
                                "sheet_name": worksheet.title,
                                "cell": cell.coordinate,
                                "value": value,
                            }
                        )
        finally:
            workbook.close()
    return locations


def _case_id(case_name: str, index: int) -> str:
    return f"case-{index}"


def _sheet_names(workbook_path: Path) -> list[str]:
    workbook = load_workbook(workbook_path, read_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def _fixme_indices_by_cell(
    workbook_path: Path,
    sheet_name: str,
    fixme_entries: Sequence[WorkbookFixmeEntry],
) -> dict[tuple[int, int], list[int]]:
    target_path = workbook_path.resolve(strict=False)
    by_cell: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, entry in enumerate(fixme_entries):
        if entry.sheet_name != sheet_name:
            continue
        if Path(entry.workbook_path).resolve(strict=False) != target_path:
            continue
        by_cell[(entry.worksheet_row, entry.fixme_column)].append(index)
    return dict(by_cell)


def _column_pixel_width(worksheet: Any, column_index: int) -> int:
    width = worksheet.column_dimensions[get_column_letter(column_index)].width
    if width is None:
        return 96
    return max(52, min(340, int(float(width) * 7.2)))


def _row_pixel_height(worksheet: Any, row_index: int) -> int:
    height = worksheet.row_dimensions[row_index].height or worksheet.sheet_format.defaultRowHeight or 15
    return max(21, min(180, int(float(height) * 1.34)))


def _record_count_mismatch_pair_starts(worksheet: Any, max_row: int, max_column: int) -> list[int]:
    common_field_rows = [
        row_index
        for row_index in range(3, max_row + 1)
        if _display_value(worksheet.cell(row_index, 1).value).strip()
        and _display_value(worksheet.cell(row_index, 2).value).strip()
    ]
    if not common_field_rows:
        return []

    mismatch_pairs: list[int] = []
    for pair_start in range(3, max_column, 2):
        if not _display_value(worksheet.cell(2, pair_start).value).strip():
            continue
        if not _display_value(worksheet.cell(2, pair_start + 1).value).strip():
            continue
        left_values = [
            _display_value(worksheet.cell(row_index, pair_start).value)
            for row_index in common_field_rows
        ]
        right_values = [
            _display_value(worksheet.cell(row_index, pair_start + 1).value)
            for row_index in common_field_rows
        ]
        left_is_missing = all(value == "" for value in left_values)
        right_is_missing = all(value == "" for value in right_values)
        if left_is_missing != right_is_missing:
            mismatch_pairs.append(pair_start)
    return mismatch_pairs


def _record_statuses(worksheet: Any, max_row: int, max_column: int, mismatch_pairs: list[int]) -> list[dict[str, Any]]:
    # Import locally: the loader also uses CompareWorkbookReference from this module.
    from .compare_workbook_loader import _is_difference

    common_field_rows = [
        row for row in range(3, max_row + 1)
        if _display_value(worksheet.cell(row, 1).value).strip()
        and _display_value(worksheet.cell(row, 2).value).strip()
    ]
    field_rows = [
        row for row in range(3, max_row + 1)
        if _display_value(worksheet.cell(row, 1).value).strip()
        or _display_value(worksheet.cell(row, 2).value).strip()
    ]
    mismatches = set(mismatch_pairs)
    statuses: list[dict[str, Any]] = []
    for pair_start in range(3, max_column, 2):
        if not _display_value(worksheet.cell(2, pair_start).value).strip():
            continue
        if not _display_value(worksheet.cell(2, pair_start + 1).value).strip():
            continue
        if pair_start in mismatches:
            left_is_missing = all(_display_value(worksheet.cell(row, pair_start).value) == "" for row in common_field_rows)
            status = STATUS_INSERT if left_is_missing else STATUS_DELETE
        elif any(_is_difference(worksheet.cell(row, pair_start), worksheet.cell(row, pair_start + 1)) for row in field_rows):
            status = STATUS_UPDATE
        else:
            status = STATUS_UNCHANGED
        statuses.append({"pair_start": pair_start, "record_number": (pair_start - 3) // 2 + 1, "status": status})
    return statuses


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value)


def _cell_style(
    cell: Any,
    context: WorkbookStyleContext,
    worksheet: Any,
    row_index: int,
    column_index: int,
    fixme_by_cell: dict[tuple[int, int], list[int]],
    compare_style: ExcelCompareStyleConfig,
) -> dict[str, str]:
    fallback = _compare_color_fallback(worksheet, row_index, column_index, fixme_by_cell, compare_style)
    background = _fill_color(cell, context)
    color = _font_color(cell, context)
    return {
        "background": background or fallback.get("background", ""),
        "color": color if color and color != "#000000" else fallback.get("color", color),
    }


def _compare_color_fallback(
    worksheet: Any,
    row_index: int,
    column_index: int,
    fixme_by_cell: dict[tuple[int, int], list[int]],
    compare_style: ExcelCompareStyleConfig,
) -> dict[str, str]:
    if row_index == 1 and column_index == 1:
        return {
            "background": _config_color(compare_style.a1_fill_color),
            "color": _config_color(compare_style.a1_font_color),
        }
    if row_index == 2 and _display_value(worksheet.cell(row_index, column_index).value).strip():
        return {
            "background": _config_color(compare_style.header_fill_color),
            "color": _config_color(compare_style.header_font_color),
        }
    if row_index >= 3 and column_index in (1, 2):
        return {
            "background": _config_color(compare_style.name_fill_color),
            "color": _config_color(compare_style.base_font_color),
        }
    if row_index >= 3 and _is_diff_value_cell(worksheet, row_index, column_index):
        return {
            "background": _config_color(compare_style.diff_fill_color),
            "color": _config_color(compare_style.diff_font_color),
        }
    if fixme_by_cell.get((row_index, column_index)):
        return {"color": _config_color(compare_style.fixme_font_color)}
    return {}


def _is_diff_value_cell(worksheet: Any, row_index: int, column_index: int) -> bool:
    if column_index < 3:
        return False
    pair_start = column_index - ((column_index - 3) % 2)
    pair_end = pair_start + 1
    if not _display_value(worksheet.cell(2, pair_start).value).strip():
        return False
    if not _display_value(worksheet.cell(2, pair_end).value).strip():
        return False
    left_value = _display_value(worksheet.cell(row_index, pair_start).value)
    right_value = _display_value(worksheet.cell(row_index, pair_end).value)
    return left_value != right_value


def _config_color(value: str) -> str:
    return _normalize_argb(str(value))


def _workbook_style_context(workbook: Any) -> WorkbookStyleContext:
    return WorkbookStyleContext(
        theme_colors=_theme_colors(workbook),
        indexed_colors=tuple(_normalize_argb(value) for value in COLOR_INDEX),
    )


def _theme_colors(workbook: Any) -> tuple[str, ...]:
    theme = getattr(workbook, "loaded_theme", None)
    if not theme:
        return _default_theme_colors()
    try:
        root = ElementTree.fromstring(theme)
    except ElementTree.ParseError:
        return _default_theme_colors()
    scheme = root.find(f".//{THEME_NS}clrScheme")
    if scheme is None:
        return _default_theme_colors()

    colors: list[str] = []
    for name in THEME_COLOR_ORDER:
        node = scheme.find(f"{THEME_NS}{name}")
        color = _theme_color_from_node(node)
        colors.append(color or _default_theme_colors()[len(colors)])
    return tuple(colors)


def _theme_color_from_node(node: Any) -> str:
    if node is None:
        return ""
    srgb = node.find(f"{THEME_NS}srgbClr")
    if srgb is not None:
        return _normalize_argb(str(srgb.attrib.get("val", "")))
    system = node.find(f"{THEME_NS}sysClr")
    if system is not None:
        return _normalize_argb(str(system.attrib.get("lastClr", "")))
    return ""


def _default_theme_colors() -> tuple[str, ...]:
    return (
        "#FFFFFF",
        "#000000",
        "#EEECE1",
        "#1F497D",
        "#4F81BD",
        "#C0504D",
        "#9BBB59",
        "#8064A2",
        "#4BACC6",
        "#F79646",
        "#0000FF",
        "#800080",
    )


def _fill_color(cell: Any, context: WorkbookStyleContext) -> str:
    fill = getattr(cell, "fill", None)
    if not fill or fill.fill_type != "solid":
        return ""
    return _color_to_css(fill.fgColor, context)


def _font_color(cell: Any, context: WorkbookStyleContext) -> str:
    font = getattr(cell, "font", None)
    return _color_to_css(getattr(font, "color", None), context)


def _color_to_css(color: Any, context: WorkbookStyleContext) -> str:
    if not color:
        return ""
    color_type = str(getattr(color, "type", "") or "")
    if color_type == "rgb":
        return _normalize_argb(str(getattr(color, "rgb", "") or ""))
    if color_type == "theme":
        theme_index = _optional_int(getattr(color, "theme", None))
        if theme_index is not None and 0 <= theme_index < len(context.theme_colors):
            return _apply_tint(context.theme_colors[theme_index], float(getattr(color, "tint", 0) or 0))
    if color_type == "indexed":
        indexed = _optional_int(getattr(color, "indexed", None))
        if indexed is not None and 0 <= indexed < len(context.indexed_colors):
            return context.indexed_colors[indexed]
    if color_type == "auto":
        return "#000000"
    return ""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_argb(value: str) -> str:
    raw = value.strip().removeprefix("#")
    if len(raw) == 8:
        raw = raw[-6:]
    if len(raw) != 6:
        return ""
    try:
        int(raw, 16)
    except ValueError:
        return ""
    return f"#{raw.upper()}"


def _apply_tint(color: str, tint: float) -> str:
    base = _normalize_argb(color)
    if not base or not tint:
        return base
    red = int(base[1:3], 16)
    green = int(base[3:5], 16)
    blue = int(base[5:7], 16)
    if tint < 0:
        factor = 1 + tint
        red = int(red * factor)
        green = int(green * factor)
        blue = int(blue * factor)
    else:
        red = int(red + (255 - red) * tint)
        green = int(green + (255 - green) * tint)
        blue = int(blue + (255 - blue) * tint)
    return f"#{_clamp_color(red):02X}{_clamp_color(green):02X}{_clamp_color(blue):02X}"


def _clamp_color(value: int) -> int:
    return min(255, max(0, value))
