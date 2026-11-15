from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.xml.constants import MAX_COLUMN, MAX_ROW

from .app_config import ExcelCompareStyleConfig, ExcelHeaderConfig, load_app_config
from .compare import SKIP_COLUMN_NAMES, SheetComparison, build_sheet_comparison, cell_value, cell_values_equal
from .compare_diagnostics import CompareDiagnosticError, compare_context, csv_location, describe_failure
from .compare_record_counts import store_record_counts
from .csv_table import CsvTable, read_csv_table

INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

COMPARE_FONT_NAME = "Yu Gothic"
COMPARE_FONT_SIZE = 11
PROCESSED_COLUMN_WIDTH = 42
FIXME_COLUMN_WIDTH = 12
INVALID_XML_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


@dataclass(frozen=True)
class WorkbookFixmeEntry:
    case_folder_name: str
    workbook_path: Path
    workbook_name: str
    csv_file_name: str
    sheet_name: str
    column_name: str
    left_value: str
    right_value: str
    record_number: int
    worksheet_row: int
    fixme_column: int

    @property
    def fixme_cell(self) -> str:
        return f"{get_column_letter(self.fixme_column)}{self.worksheet_row}"


@dataclass(frozen=True)
class CompareWorkbookWriteResult:
    output_path: Path
    sheet_count: int
    fixme_entries: list[WorkbookFixmeEntry]
    equal_before_files: list[Path]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CompareWorkbookStyles:
    base_font: Font
    header_font: Font
    diff_font: Font
    a1_font: Font
    fixme_font: Font
    a1_fill: PatternFill
    header_fill: PatternFill
    name_fill: PatternFill
    diff_fill: PatternFill


def write_compare_workbook(before_dir: Path, after_dir: Path, output_path: Path) -> int:
    return write_compare_workbook_with_fixmes(before_dir, after_dir, output_path).sheet_count


def write_compare_workbook_with_fixmes(
    before_dir: Path,
    after_dir: Path,
    output_path: Path,
    excel_headers: ExcelHeaderConfig | None = None,
    excel_style: ExcelCompareStyleConfig | None = None,
    case_folder_name: str = "",
    include_left_only_files: bool = False,
    include_right_only_files: bool = True,
    recursive: bool = False,
    omit_equal_sheets: bool = False,
    sheet_zoom: int = 85,
    key_columns_by_table: Mapping[str, tuple[str, ...]] | None = None,
) -> CompareWorkbookWriteResult:
    with compare_context("Quét danh sách CSV", **{
        "Folder trái": before_dir, "Folder phải": after_dir, "Workbook": output_path,
    }):
        pairs = _iter_compare_csv_files(
            before_dir, after_dir, include_left_only_files, include_right_only_files, recursive,
        )
    return write_compare_workbook_for_pairs(
        pairs,
        output_path,
        excel_headers=excel_headers,
        excel_style=excel_style,
        case_folder_name=case_folder_name,
        omit_equal_sheets=omit_equal_sheets,
        sheet_zoom=sheet_zoom,
        key_columns_by_table=key_columns_by_table,
    )


def write_compare_workbook_for_pairs(
    csv_pairs: list[tuple[Path, Path, str]],
    output_path: Path,
    excel_headers: ExcelHeaderConfig | None = None,
    excel_style: ExcelCompareStyleConfig | None = None,
    case_folder_name: str = "",
    omit_equal_sheets: bool = False,
    sheet_zoom: int = 85,
    key_columns_by_table: Mapping[str, tuple[str, ...]] | None = None,
) -> CompareWorkbookWriteResult:
    with compare_context("Chuẩn bị file Excel", **{"Case": case_folder_name, "Workbook": output_path}):
        app_config = None if excel_headers is not None and excel_style is not None else load_app_config()
        headers = excel_headers or app_config.excel_headers
        styles = _build_styles(excel_style or app_config.excel_compare_style)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        workbook.remove(workbook.active)

    sheet_count = 0
    used_sheet_names: set[str] = set()
    fixme_entries: list[WorkbookFixmeEntry] = []
    equal_before_files: list[Path] = []
    record_counts: dict[str, tuple[int, int]] = {}
    warnings: list[str] = []
    table_keys = {name.casefold(): columns for name, columns in (key_columns_by_table or {}).items()}
    total_cells = 0
    temporary_path: Path | None = None
    try:
        for pair_index, (before_csv, after_csv, csv_display_name) in enumerate(csv_pairs, 1):
            sheet_name = sanitize_sheet_name(Path(csv_display_name).with_suffix("").as_posix(), used_sheet_names)
            with compare_context("Compare cặp CSV", **{
                "Case": case_folder_name, "Workbook": output_path, "Sheet": sheet_name,
                "Cặp CSV": f"{pair_index}/{len(csv_pairs)}", "CSV trái": before_csv, "CSV phải": after_csv,
                "Số sheet đã xử lý": sheet_count, "Số ô dự kiến của các sheet trước": total_cells,
            }):
                before_table = read_csv_table(before_csv) if before_csv.exists() else CsvTable([], [])
                after_table = read_csv_table(after_csv) if after_csv.exists() else CsvTable([], [])
                with compare_context("Kiểm tra kích thước / ghi sheet", **{
                    "Số record trái": len(before_table.rows), "Số record phải": len(after_table.rows),
                    "Số column trái": len(before_table.headers), "Số column phải": len(after_table.headers),
                }):
                    sheet_cells = _check_sheet_dimensions(before_table, after_table)
                    warning = _header_warning(before_table, after_table, before_csv, after_csv, output_path, sheet_name)
                    if warning:
                        warnings.append(warning)
                    with compare_context("Tạo dữ liệu compare / ghi sheet", **{"Số ô dự kiến sheet": sheet_cells}):
                        table_name = Path(csv_display_name).stem
                        key_columns = table_keys.get(table_name.casefold())
                        comparison = build_sheet_comparison(table_name, before_table, after_table, key_columns=key_columns)
                        sheet_cells = _check_sheet_dimensions(before_table, after_table, len(comparison.pairs))
                        total_cells += sheet_cells
                        if comparison.fallback_reason:
                            warnings.append(str(CompareDiagnosticError(
                                "CẢNH BÁO: Không thể ghép record theo key. Đã ghép theo vị trí dòng.",
                                **{"Workbook": output_path, "Sheet": sheet_name, "Table CSV": table_name,
                                   "CSV trái": before_csv, "CSV phải": after_csv,
                                   "Key cấu hình": ", ".join(key_columns or ()) or "[không có]",
                                   "Lý do": comparison.fallback_reason},
                            )))
                        worksheet = workbook.create_sheet(sheet_name)
                        worksheet.sheet_view.zoomScale = sheet_zoom
                        sheet_entries = _write_sheet(
                            worksheet, comparison, headers, styles, case_folder_name=case_folder_name,
                            workbook_path=output_path, csv_file_name=csv_display_name,
                            before_csv=before_csv, after_csv=after_csv, before_table=before_table, after_table=after_table,
                        )
                if omit_equal_sheets and not sheet_entries:
                    workbook.remove(worksheet)
                    equal_before_files.append(before_csv)
                    continue
                fixme_entries.extend(sheet_entries)
                record_counts[sheet_name] = (len(before_table.rows), len(after_table.rows))
                sheet_count += 1

        with compare_context("Lưu workbook Excel", **{
            "Case": case_folder_name, "Workbook": output_path, "Số sheet": sheet_count,
            "Số ô dự kiến": total_cells,
        }):
            if sheet_count == 0:
                worksheet = workbook.create_sheet("Summary")
                worksheet.sheet_view.zoomScale = sheet_zoom
                _set_excel_text(worksheet["A1"], headers.no_csv_message, config_key="no_csv_message")
                worksheet["A1"].font = styles.base_font
                worksheet.column_dimensions["A"].width = 40
                record_counts["Summary"] = (0, 0)
            store_record_counts(workbook, record_counts)
            with NamedTemporaryFile(dir=output_path.parent, suffix=".xlsx", delete=False) as temporary:
                temporary_path = Path(temporary.name)
            workbook.save(temporary_path)
            preserve_compare_workbook_line_endings(temporary_path)
            temporary_path.replace(output_path)
    finally:
        workbook.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return CompareWorkbookWriteResult(
        output_path=output_path,
        sheet_count=sheet_count,
        fixme_entries=fixme_entries,
        equal_before_files=equal_before_files,
        warnings=warnings,
    )


def _check_sheet_dimensions(before: CsvTable, after: CsvTable, pair_count: int | None = None) -> int:
    columns = [name for name in dict.fromkeys([*after.headers, *before.headers]) if name not in SKIP_COLUMN_NAMES]
    records = max(len(before.rows), len(after.rows)) if pair_count is None else pair_count
    required_columns, required_rows = 4 + records * 2, 2 + len(columns)
    cells = required_columns * required_rows
    details = {"Dòng Excel cần": required_rows, "Cột Excel cần": required_columns, "Số ô dự kiến": cells}
    if required_columns > MAX_COLUMN:
        raise CompareDiagnosticError(
            "Số record CSV vượt giới hạn cột của sheet Excel.",
            hint="Mỗi record tạo 2 cột trái/phải, cộng 4 cột cho tên column, khoảng cách và FIXME. Chia CSV thành các cặp nhỏ hơn và compare riêng; không tự cắt record.",
            **details, **{"Số cặp record": records, "Record tối đa mỗi cặp CSV": (MAX_COLUMN - 4) // 2,
                         "Record đầu tiên vượt giới hạn": (MAX_COLUMN - 4) // 2 + 1, "Giới hạn cột Excel": MAX_COLUMN},
        )
    if required_rows > MAX_ROW:
        first = MAX_ROW - 2
        raise CompareDiagnosticError(
            "Số column CSV vượt giới hạn dòng của sheet Excel.",
            hint="Mỗi column CSV tạo một dòng Excel, cộng 2 dòng header. Giảm số column hoặc chia table thành các nhóm column.",
            **details, **{"Giới hạn dòng Excel": MAX_ROW, "Số column CSV tối đa": MAX_ROW - 2,
                         "Column đầu tiên vượt giới hạn": repr(columns[first])},
        )
    return cells


def _header_warning(before: CsvTable, after: CsvTable, left: Path, right: Path, output: Path, sheet: str) -> str:
    if not before.headers or not after.headers or before.headers == after.headers:
        return ""
    left_names, right_names = set(before.headers), set(after.headers)
    def missing(names, other):
        values = [f"cột {index}: {name[:120]!r}" for index, name in enumerate(names, 1) if name not in other]
        return "; ".join(values[:20]) + (f"; ... còn {len(values) - 20} column" if len(values) > 20 else "") or "Không có"
    return str(CompareDiagnosticError(
        "CẢNH BÁO: Header hai file CSV khác nhau; tiếp tục compare theo tên column.",
        hint="Kiểm tra header hai file. Column chỉ có ở một phía vẫn được đưa vào sheet, không bỏ dữ liệu.",
        **{"Workbook": output, "Sheet": sheet, "CSV trái": left, "CSV phải": right,
           "Số column trái": len(before.headers), "Số column phải": len(after.headers),
           "Chỉ có bên trái": missing(before.headers, right_names), "Chỉ có bên phải": missing(after.headers, left_names),
           "Thứ tự header": "Khác nhau" if left_names == right_names else "Tên / số lượng khác nhau"},
    ))


def _iter_compare_csv_files(
    before_dir: Path,
    after_dir: Path,
    include_left_only_files: bool,
    include_right_only_files: bool,
    recursive: bool,
) -> list[tuple[Path, Path, str]]:
    pattern = "**/*.csv" if recursive else "*.csv"
    if not include_left_only_files:
        entries: list[tuple[Path, Path, str]] = []
        for csv_path in sorted(after_dir.glob(pattern), key=lambda path: str(path).lower()):
            if not csv_path.is_file():
                continue
            relative_name = _relative_csv_name(csv_path, after_dir, recursive)
            if not include_right_only_files and not (before_dir / relative_name).is_file():
                continue
            entries.append((before_dir / relative_name, csv_path, relative_name))
        return entries

    by_name: dict[str, tuple[Path, Path, str]] = {}
    for csv_path in before_dir.glob(pattern):
        if not csv_path.is_file():
            continue
        relative_name = _relative_csv_name(csv_path, before_dir, recursive)
        by_name[relative_name.casefold()] = (csv_path, after_dir / relative_name, relative_name)
    for csv_path in after_dir.glob(pattern):
        if not csv_path.is_file():
            continue
        relative_name = _relative_csv_name(csv_path, after_dir, recursive)
        if not include_right_only_files and not (before_dir / relative_name).is_file():
            continue
        by_name[relative_name.casefold()] = (before_dir / relative_name, csv_path, relative_name)
    return [by_name[key] for key in sorted(by_name)]


def _relative_csv_name(csv_path: Path, base_dir: Path, recursive: bool) -> str:
    if not recursive:
        return csv_path.name
    return csv_path.relative_to(base_dir).as_posix()


def sanitize_sheet_name(name: str, used_names: set[str] | None = None) -> str:
    used_names = used_names if used_names is not None else set()
    base_name = INVALID_SHEET_CHARS.sub("_", name).strip()
    base_name = base_name.strip("'") or "Sheet"
    base_name = base_name[:31]

    candidate = base_name
    suffix = 1
    while candidate in used_names:
        suffix_text = f"_{suffix}"
        candidate = f"{base_name[:31 - len(suffix_text)]}{suffix_text}"
        suffix += 1

    used_names.add(candidate)
    return candidate


def _write_sheet(
    worksheet,
    comparison: SheetComparison,
    headers: ExcelHeaderConfig,
    styles: CompareWorkbookStyles,
    case_folder_name: str,
    workbook_path: Path,
    csv_file_name: str,
    before_csv: Path,
    after_csv: Path,
    before_table: CsvTable,
    after_table: CsvTable,
) -> list[WorkbookFixmeEntry]:
    total_records = len(comparison.pairs)
    fixme_entries: list[WorkbookFixmeEntry] = []

    _set_excel_text(worksheet.cell(1, 1), headers.diff_count_title, config_key="diff_count_title")
    worksheet.cell(1, 1).font = styles.a1_font
    worksheet.cell(1, 1).fill = styles.a1_fill

    _set_excel_text(worksheet.cell(2, 1), headers.left_column_title, config_key="left_column_title")
    _set_excel_text(worksheet.cell(2, 2), headers.right_column_title, config_key="right_column_title")
    _style_header(worksheet.cell(2, 1), styles)
    _style_header(worksheet.cell(2, 2), styles)

    for record_index in range(total_records):
        col_before = 3 + (record_index * 2)
        col_after = col_before + 1
        _set_excel_text(worksheet.cell(2, col_before), f"{headers.left_record_prefix}:{record_index + 1}行目", config_key="left_record_prefix")
        _set_excel_text(worksheet.cell(2, col_after), f"{headers.right_record_prefix}:{record_index + 1}行目", config_key="right_record_prefix")
        _style_header(worksheet.cell(2, col_before), styles)
        _style_header(worksheet.cell(2, col_after), styles)

    diff_field_count = 0
    fixme_col = 3 + (total_records * 2) + 1

    for row_index, column_name in enumerate(comparison.columns, start=3):
        before_name_cell = worksheet.cell(row_index, 1)
        after_name_cell = worksheet.cell(row_index, 2)
        _set_excel_text(before_name_cell, column_name if column_name in comparison.before_headers else "",
                        source=before_csv, table=before_table, column_name=column_name, side="Trái")
        _set_excel_text(after_name_cell, column_name if column_name in comparison.after_headers else "",
                        source=after_csv, table=after_table, column_name=column_name, side="Phải")
        _style_name(before_name_cell, styles)
        _style_name(after_name_cell, styles)

        has_mismatch = False
        for record_index, pair in enumerate(comparison.pairs):
            col_before = 3 + (record_index * 2)
            col_after = col_before + 1
            before_cell = worksheet.cell(row_index, col_before)
            after_cell = worksheet.cell(row_index, col_after)

            before_value = cell_value(pair.before, column_name)
            after_value = cell_value(pair.after, column_name)
            _set_excel_text(before_cell, before_value, source=before_csv, table=before_table,
                            column_name=column_name, record=pair.before_index + 1 if pair.before_index is not None else 0, side="Trái")
            _set_excel_text(after_cell, after_value, source=after_csv, table=after_table,
                            column_name=column_name, record=pair.after_index + 1 if pair.after_index is not None else 0, side="Phải")

            before_cell.font = styles.base_font
            after_cell.font = styles.base_font

            if not cell_values_equal(pair.before, pair.after, column_name):
                has_mismatch = True
                _style_diff(before_cell, styles)
                _style_diff(after_cell, styles)
                fixme_entries.append(
                    WorkbookFixmeEntry(
                        case_folder_name=case_folder_name,
                        workbook_path=workbook_path,
                        workbook_name=workbook_path.name,
                        csv_file_name=csv_file_name,
                        sheet_name=worksheet.title,
                        column_name=column_name,
                        left_value=before_value,
                        right_value=after_value,
                        record_number=record_index + 1,
                        worksheet_row=row_index,
                        fixme_column=fixme_col,
                    )
                )

        if has_mismatch:
            diff_field_count += 1
            fixme_cell = worksheet.cell(row_index, fixme_col)
            _set_excel_text(fixme_cell, headers.fixme_text, config_key="fixme_text")
            fixme_cell.font = styles.fixme_font
            fixme_cell.alignment = Alignment(wrap_text=False)

    worksheet.cell(1, 2).value = diff_field_count
    worksheet.cell(1, 2).font = styles.base_font

    worksheet.freeze_panes = "C3"
    _set_column_widths(worksheet, total_records, fixme_col)
    return fixme_entries


def _set_excel_text(cell, value: str, *, source: Path | None = None, table: CsvTable | None = None,
                    column_name: str | None = None, record: int = 0, side: str = "", config_key: str = "") -> None:
    def context():
        details = {"Giai đoạn": "Ghi ô Excel", "Sheet": cell.parent.title, "Ô Excel": cell.coordinate,
                   "File CSV": source, "Phía": side, "Mục config": config_key}
        if table is not None:
            position = table.headers.index(column_name) + 1 if column_name in table.headers else None
            lines = table.line_ranges[record] if record < len(table.line_ranges) else None
            details.update(csv_location(record, position, column_name, lines))
        return details
    if len(value) > 32767:
        raise CompareDiagnosticError(
            "Giá trị vượt giới hạn ký tự của một ô Excel.",
            hint="Kiểm tra giá trị tại record/column này và quote trong CSV. Không tự cắt bớt dữ liệu; cần rút ngắn giá trị hoặc tách dữ liệu trước khi compare.",
            **context(), **{"Số ký tự thực tế": len(value), "Giới hạn ký tự Excel": 32767},
        )
    invalid = INVALID_XML_TEXT.search(value)
    if invalid:
        raise CompareDiagnosticError(
            "Giá trị chứa ký tự không thể lưu vào file Excel/XML.",
            hint="Kiểm tra ký tự điều khiển hoặc encoding tại ô CSV này; CR, LF và TAB hợp lệ vẫn được giữ nguyên.",
            **context(), **{"Vị trí ký tự trong giá trị (từ 1)": invalid.start() + 1,
                          "Mã ký tự": f"U+{ord(invalid[0]):04X}", "Ký tự": repr(invalid[0])},
        )
    try:
        cell.value = value
    except Exception as exc:
        raise describe_failure(exc, **context()) from exc


def preserve_compare_workbook_line_endings(workbook_path: Path) -> None:
    """Keep CSV carriage returns when openpyxl serializes worksheet XML."""
    # et_xmlfile writes text-mode temporary XML. On Windows it turns each LF
    # into CRLF, so an original CRLF becomes CRCRLF. XML parsers then normalize
    # literal CRs to LF. Character references retain the original CR instead.
    carriage_return = re.compile(rb"\r(?!\n)" if os.linesep == "\r\n" else rb"\r")
    corrected_path: Path | None = None
    try:
        with ZipFile(workbook_path) as source:
            corrections: dict[str, bytes] = {}
            for info in source.infolist():
                if info.filename.startswith("xl/worksheets/") and info.filename.endswith(".xml"):
                    original = source.read(info.filename)
                    corrected = carriage_return.sub(b"&#13;", original)
                    if corrected != original:
                        corrections[info.filename] = corrected
            if not corrections:
                return
            with NamedTemporaryFile(dir=workbook_path.parent, suffix=".xlsx", delete=False) as temporary:
                corrected_path = Path(temporary.name)
            with ZipFile(corrected_path, "w") as target:
                target.comment = source.comment
                for info in source.infolist():
                    data = corrections[info.filename] if info.filename in corrections else source.read(info.filename)
                    target.writestr(info, data)
        corrected_path.replace(workbook_path)
    finally:
        if corrected_path is not None:
            corrected_path.unlink(missing_ok=True)


def _build_styles(style_config: ExcelCompareStyleConfig) -> CompareWorkbookStyles:
    return CompareWorkbookStyles(
        base_font=Font(name=COMPARE_FONT_NAME, size=COMPARE_FONT_SIZE, color=style_config.base_font_color),
        header_font=Font(name=COMPARE_FONT_NAME, size=COMPARE_FONT_SIZE, bold=True, color=style_config.header_font_color),
        diff_font=Font(name=COMPARE_FONT_NAME, size=COMPARE_FONT_SIZE, bold=True, color=style_config.diff_font_color),
        a1_font=Font(name=COMPARE_FONT_NAME, size=COMPARE_FONT_SIZE, bold=False, color=style_config.a1_font_color),
        fixme_font=Font(name=COMPARE_FONT_NAME, size=COMPARE_FONT_SIZE, bold=False, color=style_config.fixme_font_color),
        a1_fill=PatternFill("solid", fgColor=style_config.a1_fill_color),
        header_fill=PatternFill("solid", fgColor=style_config.header_fill_color),
        name_fill=PatternFill("solid", fgColor=style_config.name_fill_color),
        diff_fill=PatternFill("solid", fgColor=style_config.diff_fill_color),
    )


def _style_header(cell, styles: CompareWorkbookStyles) -> None:
    cell.font = styles.header_font
    cell.fill = styles.header_fill


def _style_name(cell, styles: CompareWorkbookStyles) -> None:
    cell.font = styles.base_font
    cell.fill = styles.name_fill


def _style_diff(cell, styles: CompareWorkbookStyles) -> None:
    cell.font = styles.diff_font
    cell.fill = styles.diff_fill


def _set_column_widths(worksheet, total_records: int, fixme_col: int) -> None:
    last_value_col = 2 + (total_records * 2)
    for column_index in range(1, last_value_col + 1):
        letter = get_column_letter(column_index)
        worksheet.column_dimensions[letter].width = PROCESSED_COLUMN_WIDTH
    worksheet.column_dimensions[get_column_letter(fixme_col)].width = FIXME_COLUMN_WIDTH
