from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

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

DIFF_COUNT_TITLE = "差分行数"
BEFORE_COLUMN_TITLE = "前列名"
AFTER_COLUMN_TITLE = "後列名"
BEFORE_RECORD_PREFIX = "前"
AFTER_RECORD_PREFIX = "後"
FIXME_TEXT = "FIXME"
PROCESSED_COLUMN_WIDTH = 42
FIXME_COLUMN_WIDTH = 12


def write_compare_workbook(before_dir: Path, after_dir: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)

    sheet_count = 0
    used_sheet_names: set[str] = set()

    for after_csv in sorted(after_dir.glob("*.csv"), key=lambda path: path.name.lower()):
        before_csv = before_dir / after_csv.name
        before_table = read_csv_table(before_csv) if before_csv.exists() else CsvTable([], [])
        after_table = read_csv_table(after_csv)
        comparison = build_sheet_comparison(after_csv.stem, before_table, after_table)

        sheet_name = sanitize_sheet_name(after_csv.stem, used_sheet_names)
        worksheet = workbook.create_sheet(sheet_name)
        _write_sheet(worksheet, comparison)
        sheet_count += 1

    if sheet_count == 0:
        worksheet = workbook.create_sheet("Summary")
        worksheet["A1"] = "No CSV files found in after folder."
        worksheet["A1"].font = BASE_FONT
        worksheet.column_dimensions["A"].width = 40

    workbook.save(output_path)
    return sheet_count


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


def _write_sheet(worksheet, comparison: SheetComparison) -> None:
    total_records = len(comparison.pairs)

    worksheet.cell(1, 1).value = DIFF_COUNT_TITLE
    worksheet.cell(1, 1).font = DIFF_FONT
    worksheet.cell(1, 1).fill = A1_FILL

    worksheet.cell(2, 1).value = BEFORE_COLUMN_TITLE
    worksheet.cell(2, 2).value = AFTER_COLUMN_TITLE
    _style_header(worksheet.cell(2, 1))
    _style_header(worksheet.cell(2, 2))

    for record_index in range(total_records):
        col_before = 3 + (record_index * 2)
        col_after = col_before + 1
        worksheet.cell(2, col_before).value = f"{BEFORE_RECORD_PREFIX}:{record_index + 1}行目"
        worksheet.cell(2, col_after).value = f"{AFTER_RECORD_PREFIX}:{record_index + 1}行目"
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

        if has_mismatch:
            diff_field_count += 1
            fixme_cell = worksheet.cell(row_index, fixme_col)
            fixme_cell.value = FIXME_TEXT
            fixme_cell.font = FIXME_FONT

    worksheet.cell(1, 2).value = diff_field_count
    worksheet.cell(1, 2).font = BASE_FONT

    worksheet.freeze_panes = "C3"
    _set_column_widths(worksheet, total_records, fixme_col)


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
