from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .app_config import ExcelCompareStyleConfig, ExcelHeaderConfig, load_app_config
from .compare import SheetComparison, build_sheet_comparison, cell_value, cell_values_equal
from .csv_table import CsvTable, read_csv_table

INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

COMPARE_FONT_NAME = "Yu Gothic"
COMPARE_FONT_SIZE = 11
PROCESSED_COLUMN_WIDTH = 42
FIXME_COLUMN_WIDTH = 12


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
    pair_by_record_order: bool = False,
    aligned_before_files: set[Path] | None = None,
    omit_equal_sheets: bool = False,
    keys_by_table: dict[str, tuple[str, ...]] | None = None,
) -> CompareWorkbookWriteResult:
    pairs = _iter_compare_csv_files(
        before_dir,
        after_dir,
        include_left_only_files,
        include_right_only_files,
        recursive,
    )
    return write_compare_workbook_for_pairs(
        pairs,
        output_path,
        excel_headers=excel_headers,
        excel_style=excel_style,
        case_folder_name=case_folder_name,
        pair_by_record_order=pair_by_record_order,
        aligned_before_files=aligned_before_files,
        omit_equal_sheets=omit_equal_sheets,
        keys_by_table=keys_by_table,
    )


def write_compare_workbook_for_pairs(
    csv_pairs: list[tuple[Path, Path, str]],
    output_path: Path,
    excel_headers: ExcelHeaderConfig | None = None,
    excel_style: ExcelCompareStyleConfig | None = None,
    case_folder_name: str = "",
    pair_by_record_order: bool = False,
    aligned_before_files: set[Path] | None = None,
    omit_equal_sheets: bool = False,
    keys_by_table: dict[str, tuple[str, ...]] | None = None,
) -> CompareWorkbookWriteResult:
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

    for before_csv, after_csv, csv_display_name in csv_pairs:
        before_table = read_csv_table(before_csv) if before_csv.exists() else CsvTable([], [])
        after_table = read_csv_table(after_csv) if after_csv.exists() else CsvTable([], [])
        comparison = build_sheet_comparison(
            Path(csv_display_name).stem, before_table, after_table,
            pair_by_record_order=pair_by_record_order or before_csv in (aligned_before_files or set()),
            key_columns=(keys_by_table or {}).get(Path(csv_display_name).stem.casefold(), ()),
        )

        sheet_name = sanitize_sheet_name(Path(csv_display_name).with_suffix("").as_posix(), used_sheet_names)
        worksheet = workbook.create_sheet(sheet_name)
        sheet_entries = _write_sheet(
            worksheet,
            comparison,
            headers,
            styles,
            case_folder_name=case_folder_name,
            workbook_path=output_path,
            csv_file_name=csv_display_name,
        )
        if omit_equal_sheets and not sheet_entries:
            workbook.remove(worksheet)
            equal_before_files.append(before_csv)
            continue
        fixme_entries.extend(sheet_entries)
        sheet_count += 1

    if sheet_count == 0:
        worksheet = workbook.create_sheet("Summary")
        worksheet["A1"] = headers.no_csv_message
        worksheet["A1"].font = styles.base_font
        worksheet.column_dimensions["A"].width = 40

    with NamedTemporaryFile(dir=output_path.parent, suffix=".xlsx", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        workbook.save(temporary_path)
        temporary_path.replace(output_path)
    finally:
        workbook.close()
        temporary_path.unlink(missing_ok=True)
    return CompareWorkbookWriteResult(
        output_path=output_path,
        sheet_count=sheet_count,
        fixme_entries=fixme_entries,
        equal_before_files=equal_before_files,
    )


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
) -> list[WorkbookFixmeEntry]:
    total_records = len(comparison.pairs)
    fixme_entries: list[WorkbookFixmeEntry] = []

    worksheet.cell(1, 1).value = headers.diff_count_title
    worksheet.cell(1, 1).font = styles.a1_font
    worksheet.cell(1, 1).fill = styles.a1_fill

    worksheet.cell(2, 1).value = headers.left_column_title
    worksheet.cell(2, 2).value = headers.right_column_title
    _style_header(worksheet.cell(2, 1), styles)
    _style_header(worksheet.cell(2, 2), styles)

    for record_index in range(total_records):
        col_before = 3 + (record_index * 2)
        col_after = col_before + 1
        worksheet.cell(2, col_before).value = f"{headers.left_record_prefix}:{record_index + 1}行目"
        worksheet.cell(2, col_after).value = f"{headers.right_record_prefix}:{record_index + 1}行目"
        _style_header(worksheet.cell(2, col_before), styles)
        _style_header(worksheet.cell(2, col_after), styles)

    diff_field_count = 0
    fixme_col = 3 + (total_records * 2) + 1

    for row_index, column_name in enumerate(comparison.columns, start=3):
        before_name_cell = worksheet.cell(row_index, 1)
        after_name_cell = worksheet.cell(row_index, 2)
        before_name_cell.value = column_name if column_name in comparison.before_headers else ""
        after_name_cell.value = column_name if column_name in comparison.after_headers else ""
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
            before_cell.value = before_value
            after_cell.value = after_value

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
            fixme_cell.value = headers.fixme_text
            fixme_cell.font = styles.fixme_font
            fixme_cell.alignment = Alignment(wrap_text=False)

    worksheet.cell(1, 2).value = diff_field_count
    worksheet.cell(1, 2).font = styles.base_font

    worksheet.freeze_panes = "C3"
    _set_column_widths(worksheet, total_records, fixme_col)
    return fixme_entries


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
