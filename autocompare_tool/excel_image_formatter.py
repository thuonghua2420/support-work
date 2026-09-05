from __future__ import annotations

import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from .app_config import ExcelImageFormatConfig, load_app_config
from .excel_format_presets import (
    FontSizeExclusionRule,
    normalize_font_size,
    parse_exclusion_rules,
)

Logger = Callable[[str], None]
SUPPORTED_EXTENSIONS = {".xls", ".xlsb", ".xlsm", ".xlsx"}
OUTPUT_FOLDER_NAME = "Formatted"
# Kept only as a visual reminder of the old hard-coded marker set; runtime
# sheet exclusion now comes from ``AppConfig.excel_image_format``.
_LEGACY_UNUSED_SHEET_MARKERS = (
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
MSO_TRUE = -1
MSO_PICTURE_TYPE_VALUES = {11, 13}  # msoLinkedPicture, msoPicture
XL_BY_ROWS = 1
XL_CENTER = -4108
XL_CONTINUOUS = 1
XL_EDGE_BOTTOM = 9
XL_EDGE_LEFT = 7
XL_EDGE_RIGHT = 10
XL_MEDIUM = -4138
XL_NEXT = 1
XL_FREE_FLOATING = 3
XL_SOLID = 1
XL_THEME_COLOR_DARK1 = 1
XL_VALUES = -4163
XL_WHOLE = 1


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


@dataclass(frozen=True)
class _ShapeSnapshot:
    shape: Any
    name: str
    top_row: int
    bottom_row: int
    left_column: int
    z_order: int
    placement: int | None


@dataclass(frozen=True)
class _SectionRows:
    input_row: int | None
    steps_row: int | None
    output_row: int | None


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
    image_config: ExcelImageFormatConfig | None = None,
    log: Logger | None = None,
) -> ExcelImageFormatSummary:
    """Resize and lay out workbook images, then normalize workbook font/view.

    The bundled VBA sample is used as a behavior reference, but this function
    implements the layout directly through Excel COM so plain ``.xlsx`` files
    can be processed without requiring an embedded macro.
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

    active_image_config = image_config or load_app_config().excel_image_format

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
                counts = _format_workbook(
                    excel,
                    workbook,
                    draw_format=draw_format,
                    run_image_format=run_image_format,
                    font_name=normalized_font_name,
                    font_size=normalized_font_size,
                    exclusion_rules=exclusion_rules,
                    image_config=active_image_config,
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
    image_config: ExcelImageFormatConfig,
    logger: Logger,
) -> _WorkbookFormatCounts:
    processed_sheets = 0
    shape_count = 0
    skipped_sheets = 0
    workbook_format_sheets = 0
    skipped_size_rows = 0
    sheet_total = int(_retry_com_call(lambda: workbook.Worksheets.Count))
    for sheet_index in range(1, sheet_total + 1):
        sheet = _retry_com_call(lambda: workbook.Worksheets.Item(sheet_index))
        sheet_name = str(_retry_com_call(lambda: sheet.Name))
        _retry_com_call(sheet.Activate)
        if run_image_format:
            if _is_excluded_image_sheet(sheet_name, image_config):
                skipped_sheets += 1
                logger(f"Bỏ qua căn ảnh trên sheet đặc biệt: {sheet_name}")
            else:
                sheet_shape_count = _retry_com_call(
                    lambda: _format_sheet_images(
                        sheet,
                        image_config=image_config,
                        draw_format=draw_format,
                        font_name=font_name,
                        logger=logger,
                    )
                )
                shape_count += sheet_shape_count
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


def _is_excluded_image_sheet(sheet_name: str, image_config: ExcelImageFormatConfig) -> bool:
    normalized_name = sheet_name.casefold()
    return any(
        marker.casefold() in normalized_name
        for marker in image_config.excluded_sheet_markers
        if marker
    )


def _format_sheet_images(
    sheet: Any,
    *,
    image_config: ExcelImageFormatConfig,
    draw_format: bool,
    font_name: str,
    logger: Logger,
) -> int:
    _apply_base_image_layout(sheet, image_config)
    sections = _find_section_rows(sheet, image_config)
    shapes = _collect_image_shapes(sheet, image_config, logger)
    if shapes:
        _validate_section_rows(sections, image_config)
        final_cursor_row = _layout_image_regions(sheet, shapes, sections, image_config)
        if draw_format:
            _apply_image_draw_format(sheet, image_config, final_cursor_row, font_name)
    return len(shapes)


def _apply_base_image_layout(sheet: Any, image_config: ExcelImageFormatConfig) -> None:
    _retry_com_call(lambda: setattr(_rows(sheet, 1), "RowHeight", image_config.first_row_height))
    _retry_com_call(lambda: setattr(_columns(sheet, image_config.marker_column), "ColumnWidth", image_config.first_column_width))


def _collect_image_shapes(
    sheet: Any,
    image_config: ExcelImageFormatConfig,
    logger: Logger,
) -> list[_ShapeSnapshot]:
    snapshots: list[_ShapeSnapshot] = []
    for collection_index, shape in enumerate(_iter_shapes(sheet.Shapes), start=1):
        if not _is_image_shape(shape, image_config):
            continue
        snapshot = _snapshot_shape(shape, collection_index, logger)
        if snapshot is None:
            continue
        snapshots.append(snapshot)
    # Excel's lower z-order is the earlier pasted, lower image in an overlap stack.
    snapshots.sort(key=lambda item: (item.z_order, item.name.casefold()))
    return snapshots


def _iter_shapes(shapes: Any) -> Iterator[Any]:
    count = int(_retry_com_call(lambda: shapes.Count))
    for index in range(1, count + 1):
        yield _retry_com_call(lambda index=index: shapes.Item(index))


def _is_image_shape(shape: Any, image_config: ExcelImageFormatConfig) -> bool:
    try:
        shape_type = int(_retry_com_call(lambda: shape.Type))
    except Exception:
        shape_type = None
    if shape_type in MSO_PICTURE_TYPE_VALUES:
        return True

    try:
        name = str(_retry_com_call(lambda: shape.Name)).casefold()
    except Exception:
        return False
    return any(marker.casefold() in name for marker in image_config.shape_name_markers if marker)


def _snapshot_shape(shape: Any, collection_index: int, logger: Logger) -> _ShapeSnapshot | None:
    try:
        name = str(_retry_com_call(lambda: shape.Name))
        top_cell = _retry_com_call(lambda: shape.TopLeftCell)
        bottom_cell = _retry_com_call(lambda: shape.BottomRightCell)
        top_row = int(_retry_com_call(lambda: top_cell.Row))
        bottom_row = int(_retry_com_call(lambda: bottom_cell.Row))
        left_column = int(_retry_com_call(lambda: top_cell.Column))
        try:
            z_order = int(_retry_com_call(lambda: shape.ZOrderPosition))
        except Exception:
            z_order = collection_index
        try:
            placement = int(_retry_com_call(lambda: shape.Placement))
        except Exception:
            placement = None
    except Exception as exc:
        logger(f"Bỏ qua shape không đọc được vị trí: {exc}")
        return None
    return _ShapeSnapshot(
        shape=shape,
        name=name,
        top_row=top_row,
        bottom_row=max(top_row, bottom_row),
        left_column=left_column,
        z_order=z_order,
        placement=placement,
    )


def _find_section_rows(sheet: Any, image_config: ExcelImageFormatConfig) -> _SectionRows:
    return _SectionRows(
        input_row=_find_marker_row(sheet, image_config.input_marker, image_config.marker_column),
        steps_row=_find_marker_row(sheet, image_config.steps_marker, image_config.marker_column),
        output_row=_find_marker_row(sheet, image_config.output_marker, image_config.marker_column),
    )


def _validate_section_rows(sections: _SectionRows, image_config: ExcelImageFormatConfig) -> None:
    markers = (
        (image_config.input_marker, sections.input_row),
        (image_config.steps_marker, sections.steps_row),
        (image_config.output_marker, sections.output_row),
    )
    missing = [name for name, row in markers if row is None]
    if missing:
        raise ValueError(f"Không tìm thấy marker phân vùng tại cột cấu hình: {', '.join(missing)}.")
    rows = [row for _name, row in markers if row is not None]
    if rows != sorted(rows) or len(set(rows)) != len(rows):
        raise ValueError("Marker vùng phải xuất hiện theo thứ tự Input, Steps, Output từ trên xuống dưới.")


def _find_marker_row(sheet: Any, marker: str, marker_column: int) -> int | None:
    if not marker:
        return None
    column_address = f"{_column_name(marker_column)}:{_column_name(marker_column)}"
    found = _retry_com_call(
        lambda: sheet.Range(column_address).Find(
            What=marker,
            LookIn=XL_VALUES,
            LookAt=XL_WHOLE,
            SearchOrder=XL_BY_ROWS,
            SearchDirection=XL_NEXT,
            MatchCase=False,
            SearchFormat=False,
        )
    )
    if found is None:
        return None
    return int(_retry_com_call(lambda: found.Row))


def _layout_image_regions(
    sheet: Any,
    snapshots: list[_ShapeSnapshot],
    sections: _SectionRows,
    image_config: ExcelImageFormatConfig,
) -> int:
    """Lay out three row sections independently for the old and new systems."""

    if image_config.left_group_start_column < 1:
        raise ValueError("Cột bắt đầu của hệ thống cũ phải lớn hơn hoặc bằng 1.")
    if image_config.left_group_end_column >= image_config.right_group_start_column:
        raise ValueError("Vùng cột hệ thống cũ phải kết thúc trước vùng cột hệ thống mới.")

    grouped: dict[tuple[int, int], list[_ShapeSnapshot]] = {
        (row_region, column_region): []
        for row_region in range(3)
        for column_region in range(2)
    }
    for snapshot in snapshots:
        row_region = _region_for_row(snapshot.top_row, sections)
        if image_config.left_group_start_column <= snapshot.left_column <= image_config.left_group_end_column:
            column_region = 0
        elif snapshot.left_column >= image_config.right_group_start_column:
            column_region = 1
        else:
            raise ValueError(
                f"Ảnh {snapshot.name} có góc trên bên trái tại cột {snapshot.left_column}, "
                "nằm ngoài hai vùng cột đã cấu hình."
            )
        grouped[(row_region, column_region)].append(snapshot)
        try:
            _retry_com_call(lambda snapshot=snapshot: setattr(snapshot.shape, "Placement", XL_FREE_FLOATING))
        except Exception:
            pass

    widths = (
        _range_width(sheet, image_config.left_width_range),
        _range_width(sheet, image_config.right_width_range),
    )
    for column_region, width in enumerate(widths):
        for row_region in range(3):
            for snapshot in grouped[(row_region, column_region)]:
                _resize_shape(snapshot.shape, width)

    _resize_row_regions(sheet, grouped, image_config)
    sections = _find_section_rows(sheet, image_config)
    gap_points = max(image_config.image_spacing_pixels, 0) * 72 / 96
    final_bottom_row = 1

    for row_region in range(3):
        header_row = _section_header_row(row_region, sections)
        if header_row is None:
            continue
        target_row = max(header_row + max(image_config.image_row_padding, 0), 1)
        for column_region, anchor_column in enumerate(
            (image_config.left_anchor_column, image_config.right_anchor_column)
        ):
            target_cell = _retry_com_call(lambda: sheet.Cells.Item(target_row, anchor_column))
            target_top = float(_retry_com_call(lambda: target_cell.Top))
            target_left = float(_retry_com_call(lambda: target_cell.Left))
            for snapshot in grouped[(row_region, column_region)]:
                _retry_com_call(lambda snapshot=snapshot: setattr(snapshot.shape, "Left", target_left))
                _retry_com_call(
                    lambda snapshot=snapshot, target_top=target_top: setattr(snapshot.shape, "Top", target_top)
                )
                final_bottom_row = max(final_bottom_row, _shape_bottom_row(snapshot.shape))
                target_top += _shape_height(snapshot.shape) + gap_points

    for snapshot in snapshots:
        if snapshot.placement is not None:
            _retry_com_call(
                lambda snapshot=snapshot: setattr(snapshot.shape, "Placement", snapshot.placement)
            )

    return final_bottom_row + max(image_config.image_row_padding, 0)


def _resize_row_regions(
    sheet: Any,
    grouped: dict[tuple[int, int], list[_ShapeSnapshot]],
    image_config: ExcelImageFormatConfig,
) -> None:
    padding_rows = max(image_config.image_row_padding, 0)
    gap_points = max(image_config.image_spacing_pixels, 0) * 72 / 96
    scan_columns = max(
        image_config.value_scan_column_count,
        image_config.bottom_border_last_column,
        image_config.right_group_start_column,
        1,
    )

    for row_region in range(3):
        sections = _find_section_rows(sheet, image_config)
        header_row = _section_header_row(row_region, sections)
        if header_row is None:
            continue
        next_marker_row = _next_marker_row(row_region, sections)
        section_end = next_marker_row - 1 if next_marker_row is not None else _used_range_bottom_row(sheet)
        content_last_row = _last_value_row(sheet, header_row + 1, section_end, scan_columns)
        first_image_row = max(header_row + padding_rows, 1)
        first_image_top = _cell_top(sheet, first_image_row, 1)
        tallest_stack = max(
            _stack_height(grouped[(row_region, 0)], gap_points),
            _stack_height(grouped[(row_region, 1)], gap_points),
        )
        image_last_row = header_row
        if tallest_stack > 0:
            image_last_row = _row_at_or_after_top(sheet, first_image_row, first_image_top + tallest_stack)
        desired_end_row = max(header_row + padding_rows, content_last_row, image_last_row)

        if next_marker_row is None:
            _shrink_trailing_empty_rows(sheet, desired_end_row, section_end, scan_columns)
            continue

        desired_marker_row = desired_end_row + padding_rows
        if desired_marker_row > next_marker_row:
            count = desired_marker_row - next_marker_row
            _retry_com_call(lambda: _rows(sheet, f"{next_marker_row}:{next_marker_row + count - 1}").Insert())
        elif desired_marker_row < next_marker_row:
            delete_start = desired_marker_row
            delete_end = next_marker_row - 1
            if _rows_are_empty(sheet, delete_start, delete_end, scan_columns):
                _retry_com_call(lambda: _rows(sheet, f"{delete_start}:{delete_end}").Delete())


def _section_header_row(region: int, sections: _SectionRows) -> int | None:
    return (sections.input_row, sections.steps_row, sections.output_row)[region]


def _stack_height(snapshots: list[_ShapeSnapshot], gap_points: float) -> float:
    if not snapshots:
        return 0.0
    return sum(_shape_height(snapshot.shape) for snapshot in snapshots) + gap_points * (len(snapshots) - 1)


def _shape_height(shape: Any) -> float:
    try:
        return max(float(_retry_com_call(lambda: shape.Height)), 0.0)
    except Exception:
        return _shape_row_span(shape) * 15.0


def _cell_top(sheet: Any, row: int, column: int) -> float:
    cell = _retry_com_call(lambda: sheet.Cells.Item(row, column))
    return float(_retry_com_call(lambda: cell.Top))


def _row_at_or_after_top(sheet: Any, start_row: int, target_top: float) -> int:
    low = max(start_row, 1)
    if _cell_top(sheet, low, 1) >= target_top:
        return low

    high = min(low + 1, 1_048_576)
    step = 1
    while high < 1_048_576 and _cell_top(sheet, high, 1) < target_top:
        low = high
        step *= 2
        high = min(high + step, 1_048_576)

    while low + 1 < high:
        middle = (low + high) // 2
        if _cell_top(sheet, middle, 1) < target_top:
            low = middle
        else:
            high = middle
    return high


def _used_range_bottom_row(sheet: Any) -> int:
    used_range = _retry_com_call(lambda: sheet.UsedRange)
    first_row = int(_retry_com_call(lambda: used_range.Row))
    row_count = int(_retry_com_call(lambda: used_range.Rows.Count))
    return max(first_row + row_count - 1, 1)


def _rows_are_empty(sheet: Any, start_row: int, end_row: int, column_count: int) -> bool:
    if end_row < start_row:
        return True
    return _last_value_row(sheet, start_row, end_row, column_count) == 0


def _shrink_trailing_empty_rows(
    sheet: Any,
    desired_end_row: int,
    current_end_row: int,
    column_count: int,
) -> None:
    if desired_end_row >= current_end_row:
        return
    delete_start = desired_end_row + 1
    if _rows_are_empty(sheet, delete_start, current_end_row, column_count):
        _retry_com_call(lambda: _rows(sheet, f"{delete_start}:{current_end_row}").Delete())


def _region_for_row(row: int, sections: _SectionRows) -> int:
    region = 0
    if sections.steps_row is not None and row >= sections.steps_row:
        region = 1
    if sections.output_row is not None and row >= sections.output_row:
        region = 2
    return region


def _next_marker_row(region: int, sections: _SectionRows) -> int | None:
    candidates: list[int] = []
    if region < 1 and sections.steps_row is not None:
        candidates.append(sections.steps_row)
    if region < 2 and sections.output_row is not None:
        candidates.append(sections.output_row)
    return min(candidates) if candidates else None


def _rows(sheet: Any, selector: int | str) -> Any:
    try:
        return sheet.Rows(selector)
    except TypeError:
        return sheet.Rows.Item(selector)


def _columns(sheet: Any, selector: int | str) -> Any:
    try:
        return sheet.Columns(selector)
    except TypeError:
        return sheet.Columns.Item(selector)


def _resize_shape(shape: Any, width: float) -> None:
    if width <= 0:
        return
    try:
        _retry_com_call(lambda: setattr(shape, "LockAspectRatio", MSO_TRUE))
    except Exception:
        pass
    _retry_com_call(lambda: setattr(shape, "Width", width))


def _shape_top_row(shape: Any, fallback: int = 1) -> int:
    try:
        return int(_retry_com_call(lambda: shape.TopLeftCell.Row))
    except Exception:
        return fallback


def _shape_bottom_row(shape: Any) -> int:
    try:
        return int(_retry_com_call(lambda: shape.BottomRightCell.Row))
    except Exception:
        return _shape_top_row(shape)


def _shape_row_span(shape: Any) -> int:
    top_row = _shape_top_row(shape)
    bottom_row = _shape_bottom_row(shape)
    return max(bottom_row - top_row + 1, 1)


def _range_width(sheet: Any, address: str) -> float:
    try:
        return float(_retry_com_call(lambda: sheet.Range(address).Width))
    except Exception:
        return 0.0


def _last_value_row(sheet: Any, start_row: int, end_row: int, column_count: int) -> int:
    if end_row < start_row:
        return 0
    for row in range(end_row, start_row - 1, -1):
        for column in range(1, max(column_count, 1) + 1):
            value = _retry_com_call(lambda row=row, column=column: sheet.Cells.Item(row, column).Value2)
            if value is not None and str(value) != "":
                return row
    return 0


def _apply_image_draw_format(
    sheet: Any,
    image_config: ExcelImageFormatConfig,
    final_cursor_row: int,
    font_name: str,
) -> None:
    if image_config.draw_background:
        _apply_image_background(sheet, image_config)
    if image_config.draw_header:
        _apply_image_header(sheet, image_config, font_name)
    if image_config.draw_borders:
        _apply_image_borders(sheet, image_config, final_cursor_row)


def _apply_image_background(sheet: Any, image_config: ExcelImageFormatConfig) -> None:
    try:
        cells_interior = sheet.Cells.Interior
        cells_interior.Pattern = XL_SOLID
        cells_interior.ThemeColor = XL_THEME_COLOR_DARK1
        cells_interior.TintAndShade = 0
        cells_interior.PatternTintAndShade = 0
    except Exception:
        pass
    header_range = _retry_com_call(lambda: sheet.Range(image_config.header_fill_range))
    header_range.Interior.Pattern = XL_SOLID
    header_range.Interior.Color = image_config.header_fill_color
    header_range.Interior.TintAndShade = 0
    header_range.Interior.PatternTintAndShade = 0


def _apply_image_header(sheet: Any, image_config: ExcelImageFormatConfig, font_name: str) -> None:
    left_header = _retry_com_call(lambda: sheet.Range(image_config.left_header_range))
    right_header = _retry_com_call(lambda: sheet.Range(image_config.right_header_range))
    for header_range in (left_header, right_header):
        header_range.HorizontalAlignment = XL_CENTER
        header_range.VerticalAlignment = XL_CENTER
        try:
            header_range.Merge()
        except Exception:
            pass
    left_header.Value = image_config.left_header_text
    right_header.Value = image_config.right_header_text
    header_range = _retry_com_call(lambda: sheet.Range(image_config.header_fill_range))
    header_range.Font.Name = font_name
    header_range.Font.Size = image_config.header_font_size
    header_range.Font.Bold = True


def _apply_image_borders(sheet: Any, image_config: ExcelImageFormatConfig, final_cursor_row: int) -> None:
    bottom_row = max(final_cursor_row - 1, image_config.border_start_row)
    _set_border(
        _range_from_cells(
            sheet,
            image_config.border_start_row,
            image_config.separator_column,
            bottom_row,
            image_config.separator_column,
        ),
        XL_EDGE_LEFT,
    )
    _set_border(
        _range_from_cells(
            sheet,
            image_config.border_start_row,
            image_config.right_border_column,
            bottom_row,
            image_config.right_border_column,
        ),
        XL_EDGE_RIGHT,
    )
    _set_border(
        _range_from_cells(
            sheet,
            bottom_row,
            1,
            bottom_row,
            image_config.bottom_border_last_column,
        ),
        XL_EDGE_BOTTOM,
    )


def _range_from_cells(sheet: Any, start_row: int, start_column: int, end_row: int, end_column: int) -> Any:
    start_cell = _retry_com_call(lambda: sheet.Cells.Item(start_row, start_column))
    end_cell = _retry_com_call(lambda: sheet.Cells.Item(end_row, end_column))
    return _retry_com_call(lambda: sheet.Range(start_cell, end_cell))


def _set_border(target_range: Any, edge: int) -> None:
    border = target_range.Borders(edge)
    border.LineStyle = XL_CONTINUOUS
    border.Weight = XL_MEDIUM


def _column_name(column: int) -> str:
    result = ""
    while column > 0:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


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
