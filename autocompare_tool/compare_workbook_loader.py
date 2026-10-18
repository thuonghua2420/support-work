"""Discover previously generated UT compare workbooks without changing them."""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from zipfile import BadZipFile

from openpyxl import load_workbook

from .app_config import AppConfig
from .compare_workbook_view import CompareWorkbookReference
from .excel_writer import WorkbookFixmeEntry
from .processor import discover_test_cases


def load_ut_compare_workbooks(
    root: str | Path,
    config: AppConfig,
    log: Callable[[str], None] = lambda _message: None,
) -> tuple[list[CompareWorkbookReference], list[WorkbookFixmeEntry]]:
    if not str(root).strip():
        raise ValueError("Vui lòng chọn một case hoặc folder cha chứa các case.")
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise ValueError(f"Thư mục gốc không tồn tại: {root_path}")
    case_paths = discover_test_cases(root_path, config.folders.case_pattern, output_dir=config.folders.output_dir)
    if not case_paths:
        raise ValueError(f"Không tìm thấy folder case khớp mẫu {config.folders.case_pattern!r} trong: {root_path}")

    references: list[CompareWorkbookReference] = []
    entries: list[WorkbookFixmeEntry] = []
    for case_path in case_paths:
        compare_dir = case_path / config.folders.output_dir / config.folders.compare_dir
        if not compare_dir.is_dir():
            continue
        for workbook_path in sorted(compare_dir.iterdir(), key=lambda path: path.name.lower()):
            if not workbook_path.is_file() or workbook_path.suffix.lower() != ".xlsx" or workbook_path.name.startswith("~$"):
                continue
            reference = CompareWorkbookReference(case_path.name, workbook_path, workbook_path.name)
            try:
                workbook_entries = _read_compare_entries(reference, config)
            except (OSError, ValueError, KeyError, BadZipFile) as exc:
                log(f"Bỏ qua {workbook_path}: {exc}")
                continue
            references.append(reference)
            entries.extend(workbook_entries)
            log(f"[{case_path.name}] Đã nạp {workbook_path.name} ({len(workbook_entries)} sai khác).")

    if not references:
        raise ValueError(f"Không tìm thấy workbook Compare hợp lệ trong {config.folders.output_dir}/{config.folders.compare_dir} của các case {config.folders.case_pattern!r}: {root_path}")
    return references, entries


def _read_compare_entries(reference: CompareWorkbookReference, config: AppConfig) -> list[WorkbookFixmeEntry]:
    workbook = load_workbook(reference.workbook_path, read_only=False, data_only=False)
    try:
        headers = [config.excel_headers, *config.excel_headers_by_workflow.values()]
        entries: list[WorkbookFixmeEntry] = []
        for sheet in workbook.worksheets:
            a1 = sheet.cell(1, 1).value
            if any(a1 == header.no_csv_message for header in headers):
                continue
            matches_current_headers = any(
                a1 == header.diff_count_title
                and sheet.cell(2, 1).value == header.left_column_title
                and sheet.cell(2, 2).value == header.right_column_title
                for header in headers
            )
            matches_saved_layout = (
                bool(a1)
                and isinstance(sheet.cell(1, 2).value, int)
                and bool(sheet.cell(2, 1).value)
                and bool(sheet.cell(2, 2).value)
                and sheet.max_row >= 3
            )
            if not (matches_current_headers or matches_saved_layout):
                raise ValueError(f"Sheet {sheet.title} không có cấu trúc Compare")

            pair_starts: list[int] = []
            column = 3
            while sheet.cell(2, column).value is not None and sheet.cell(2, column + 1).value is not None:
                pair_starts.append(column)
                column += 2
            fixme_column = column + 1
            for row in range(3, sheet.max_row + 1):
                column_name = sheet.cell(row, 1).value or sheet.cell(row, 2).value
                if not column_name:
                    continue
                for record_number, pair_start in enumerate(pair_starts, start=1):
                    left = sheet.cell(row, pair_start)
                    right = sheet.cell(row, pair_start + 1)
                    if not _is_difference(left, right):
                        continue
                    entries.append(WorkbookFixmeEntry(
                        case_folder_name=reference.case_folder_name,
                        workbook_path=reference.workbook_path,
                        workbook_name=reference.workbook_name,
                        csv_file_name=f"{sheet.title}.csv",
                        sheet_name=sheet.title,
                        column_name=str(column_name),
                        left_value="" if left.value is None else str(left.value),
                        right_value="" if right.value is None else str(right.value),
                        record_number=record_number,
                        worksheet_row=row,
                        fixme_column=fixme_column,
                    ))
        return entries
    finally:
        workbook.close()


def _is_difference(left: object, right: object) -> bool:
    if left.value != right.value:
        return True
    # Some different CSV values render identically in Excel (for example an
    # absent record and an empty cell). The generated workbook marks both
    # paired cells with the same solid difference fill.
    left_fill = left.fill
    right_fill = right.fill
    if left_fill.patternType != "solid" or right_fill.patternType != "solid":
        return False
    if left_fill.fgColor != right_fill.fgColor:
        return False
    return True
