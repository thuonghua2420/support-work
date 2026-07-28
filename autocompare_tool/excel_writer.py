from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .app_config import ExcelHeaderConfig, load_app_config
from .compare import SheetComparison, build_sheet_comparison, cell_value
from .csv_table import CsvTable, read_csv_table

INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

BASE_FONT = Font(name="Yu Gothic", size=11, color="000000")
HEADER_FONT = Font(name="Yu Gothic", size=11, bold=True, color="000000")
DIFF_FONT = Font(name="Yu Gothic", size=11, color="9C0006")
FIXME_FONT = Font(name="Yu Gothic", size=11, bold=True, color="000000")

A1_FILL = PatternFill("solid", fgColor="FFC7CE")
HEADER_FILL = PatternFill("solid", fgColor="C6EFCE")
NAME_FILL = PatternFill("solid", fgColor="E2EFDA")
DIFF_FILL = PatternFill("solid", fgColor="E5CCFF")

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


def write_compare_workbook(before_dir: Path, after_dir: Path, output_path: Path) -> int:
    return write_compare_workbook_with_fixmes(before_dir, after_dir, output_path).sheet_count


def write_compare_workbook_with_fixmes(
    before_dir: Path,
    after_dir: Path,
    output_path: Path,
    excel_headers: ExcelHeaderConfig | None = None,
    case_folder_name: str = "",
    include_left_only_files: bool = False,
) -> CompareWorkbookWriteResult:
    headers = excel_headers or load_app_config().excel_headers
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)

    sheet_count = 0
    used_sheet_names: set[str] = set()
    fixme_entries: list[WorkbookFixmeEntry] = []

    for after_csv in _iter_compare_csv_files(before_dir, after_dir, include_left_only_files):
        before_csv = before_dir / after_csv.name
        before_table = read_csv_table(before_csv) if before_csv.exists() else CsvTable([], [])
        after_table = read_csv_table(after_csv) if after_csv.exists() else CsvTable([], [])
        comparison = build_sheet_comparison(after_csv.stem, before_table, after_table)

        sheet_name = sanitize_sheet_name(after_csv.stem, used_sheet_names)
        worksheet = workbook.create_sheet(sheet_name)
        fixme_entries.extend(
            _write_sheet(
                worksheet,
                comparison,
                headers,
                case_folder_name=case_folder_name,
                workbook_path=output_path,
                csv_file_name=after_csv.name,
            )
        )
        sheet_count += 1

    if sheet_count == 0:
        worksheet = workbook.create_sheet("Summary")
        worksheet["A1"] = headers.no_csv_message
        worksheet["A1"].font = BASE_FONT
        worksheet.column_dimensions["A"].width = 40

    workbook.save(output_path)
    return CompareWorkbookWriteResult(output_path=output_path, sheet_count=sheet_count, fixme_entries=fixme_entries)


def _iter_compare_csv_files(before_dir: Path, after_dir: Path, include_left_only_files: bool) -> list[Path]:
    if not include_left_only_files:
        return sorted(after_dir.glob("*.csv"), key=lambda path: path.name.lower())

    by_name: dict[str, Path] = {}
    for csv_path in before_dir.glob("*.csv"):
        by_name[csv_path.name.lower()] = after_dir / csv_path.name
    for csv_path in after_dir.glob("*.csv"):
        by_name[csv_path.name.lower()] = csv_path
    return [by_name[key] for key in sorted(by_name)]


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
    case_folder_name: str,
    workbook_path: Path,
    csv_file_name: str,
) -> list[WorkbookFixmeEntry]:
    total_records = len(comparison.pairs)
    fixme_entries: list[WorkbookFixmeEntry] = []

    worksheet.cell(1, 1).value = headers.diff_count_title
    worksheet.cell(1, 1).font = DIFF_FONT
    worksheet.cell(1, 1).fill = A1_FILL

    worksheet.cell(2, 1).value = headers.left_column_title
    worksheet.cell(2, 2).value = headers.right_column_title
    _style_header(worksheet.cell(2, 1))
    _style_header(worksheet.cell(2, 2))

    for record_index in range(total_records):
        col_before = 3 + (record_index * 2)
        col_after = col_before + 1
        worksheet.cell(2, col_before).value = f"{headers.left_record_prefix}:{record_index + 1}行目"
        worksheet.cell(2, col_after).value = f"{headers.right_record_prefix}:{record_index + 1}行目"
        _style_header(worksheet.cell(2, col_before))
        _style_header(worksheet.cell(2, col_after))

    diff_field_count = 0
    fixme_col = 3 + (total_records * 2) + 1

    for row_index, column_name in enumerate(comparison.columns, start=3):
        before_name_cell = worksheet.cell(row_index, 1)
        after_name_cell = worksheet.cell(row_index, 2)
        before_name_cell.value = column_name if column_name in comparison.before_headers else ""
        after_name_cell.value = column_name if column_name in comparison.after_headers else ""
        _style_name(before_name_cell)
        _style_name(after_name_cell)

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

            before_cell.font = BASE_FONT
            after_cell.font = BASE_FONT

            if before_value != after_value:
                has_mismatch = True
                _style_diff(before_cell)
                _style_diff(after_cell)
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
            fixme_cell.font = FIXME_FONT

    worksheet.cell(1, 2).value = diff_field_count
    worksheet.cell(1, 2).font = BASE_FONT

    worksheet.freeze_panes = "C3"
    _set_column_widths(worksheet, total_records, fixme_col)
    return fixme_entries


def _style_header(cell) -> None:
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL


def _style_name(cell) -> None:
    cell.font = BASE_FONT
    cell.fill = NAME_FILL


def _style_diff(cell) -> None:
    cell.font = DIFF_FONT
    cell.fill = DIFF_FILL


def _set_column_widths(worksheet, total_records: int, fixme_col: int) -> None:
    last_value_col = 2 + (total_records * 2)
    for column_index in range(1, last_value_col + 1):
        letter = get_column_letter(column_index)
        worksheet.column_dimensions[letter].width = PROCESSED_COLUMN_WIDTH
    worksheet.column_dimensions[get_column_letter(fixme_col)].width = FIXME_COLUMN_WIDTH
