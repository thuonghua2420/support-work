from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover
    load_workbook = None


SQL_NUMBER_PATTERN = re.compile(r"^\s*(?:SQL\s*)?(?:No\.?\s*)?(\d+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ExcelSqlEntry:
    number: str
    sql_text: str
    start_row: int
    end_row: int


def load_sql_entries_from_excel(excel_path: str | Path, sheet_name: str) -> list[ExcelSqlEntry]:
    if load_workbook is None:
        raise RuntimeError("Thiếu thư viện openpyxl nên không thể đọc file Excel.")
    path = Path(excel_path).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"File Excel không tồn tại: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        raise ValueError("Chỉ hỗ trợ đọc workbook .xlsx/.xlsm/.xltx/.xltm bằng openpyxl.")

    workbook = load_workbook(path, read_only=False, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            available = ", ".join(workbook.sheetnames)
            raise ValueError(f"Không tìm thấy sheet “{sheet_name}”. Sheet hiện có: {available}")
        worksheet = workbook[sheet_name]
        return _read_sql_entries(worksheet)
    finally:
        workbook.close()


def render_raw_sql_entries(entries: list[ExcelSqlEntry]) -> str:
    return "\n\n".join(f"-- SQL No.{entry.number}\n{_ensure_semicolon(entry.sql_text)}" for entry in entries)


def _read_sql_entries(worksheet: Any) -> list[ExcelSqlEntry]:
    starts: list[tuple[int, str]] = []
    for row_index in range(1, worksheet.max_row + 1):
        number = _sql_number(worksheet.cell(row_index, 1).value)
        if number:
            starts.append((row_index, number))
    if not starts:
        raise ValueError("Không tìm thấy số thứ tự SQL ở cột A.")

    entries: list[ExcelSqlEntry] = []
    for index, (start_row, number) in enumerate(starts):
        limit_row = starts[index + 1][0] - 1 if index + 1 < len(starts) else worksheet.max_row
        end_row = _border_end_row(worksheet, start_row, limit_row) or limit_row
        sql_text = _collect_sql_text(worksheet, start_row, end_row)
        if not sql_text:
            raise ValueError(f"SQL No.{number} không có nội dung ở cột B trở đi.")
        entries.append(ExcelSqlEntry(number=number, sql_text=sql_text, start_row=start_row, end_row=end_row))
    return entries


def _border_end_row(worksheet: Any, start_row: int, limit_row: int) -> int | None:
    for row_index in range(start_row, limit_row + 1):
        if not _row_has_sql_content(worksheet, row_index):
            continue
        if not _row_has_bottom_border(worksheet, row_index):
            continue
        next_row = row_index + 1
        if next_row > limit_row or _sql_number(worksheet.cell(next_row, 1).value) or not _row_has_sql_content(worksheet, next_row):
            return row_index
    return None


def _collect_sql_text(worksheet: Any, start_row: int, end_row: int) -> str:
    lines: list[str] = []
    for row_index in range(start_row, end_row + 1):
        parts = [
            _cell_text(worksheet.cell(row_index, col_index).value)
            for col_index in range(2, worksheet.max_column + 1)
        ]
        parts = [part for part in parts if part]
        if parts:
            lines.append(" ".join(parts))
    return "\n".join(lines).strip()


def _row_has_sql_content(worksheet: Any, row_index: int) -> bool:
    return any(_cell_text(worksheet.cell(row_index, col_index).value) for col_index in range(2, worksheet.max_column + 1))


def _row_has_bottom_border(worksheet: Any, row_index: int) -> bool:
    for col_index in range(1, worksheet.max_column + 1):
        side = worksheet.cell(row_index, col_index).border.bottom
        if side is not None and side.style:
            return True
    return False


def _sql_number(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    match = SQL_NUMBER_PATTERN.match(str(value))
    return match.group(1) if match else ""


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _ensure_semicolon(sql_text: str) -> str:
    value = sql_text.strip()
    return value if value.endswith(";") else f"{value};"
