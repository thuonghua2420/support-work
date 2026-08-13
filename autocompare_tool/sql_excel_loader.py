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
class ExcelSqlLine:
    row: int
    sql_text: str
    note: str = ""


@dataclass(frozen=True)
class ExcelSqlEntry:
    number: str
    sql_text: str
    start_row: int
    end_row: int
    sql_lines: tuple[ExcelSqlLine, ...] = ()


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
    blocks: list[str] = []
    for entry in entries:
        lines = [f"-- SQL No.{entry.number}"]
        if entry.sql_lines:
            for sql_line in entry.sql_lines:
                if sql_line.note:
                    lines.append(_comment_line(sql_line.note))
                lines.append(sql_line.sql_text)
            blocks.append(_ensure_semicolon("\n".join(lines)))
        else:
            blocks.append(f"-- SQL No.{entry.number}\n{_ensure_semicolon(entry.sql_text)}")
    return "\n\n".join(blocks)


def format_excel_sql_entries(
    entries: list[ExcelSqlEntry],
    dialect: str = "",
    log: Any | None = None,
) -> Any:
    from .sql_tools import SqlFormatResult, format_sql

    logger = log or (lambda _message: None)
    blocks: list[str] = []
    statement_count = 0
    result_dialect = "auto"
    for entry in entries:
        try:
            formatted = format_sql(entry.sql_text, dialect=dialect)
        except ValueError as exc:
            raise ValueError(f"SQL No.{entry.number} không hợp lệ: {exc}") from exc
        statement_count += formatted.statement_count
        result_dialect = formatted.dialect
        blocks.append(f"-- SQL No.{entry.number}\n{_insert_note_comments(formatted.formatted_sql, entry.sql_lines)}")
    if not blocks:
        raise ValueError("Không tìm thấy câu SQL nào để format.")
    logger(f"Đã format {len(entries)} SQL từ Excel ({statement_count} statement).")
    return SqlFormatResult(
        formatted_sql="\n\n".join(blocks),
        statement_count=statement_count,
        dialect=result_dialect,
    )


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
        sql_text, sql_lines = _collect_sql_text(worksheet, start_row, end_row)
        if not sql_text:
            raise ValueError(f"SQL No.{number} không có nội dung ở cột B.")
        entries.append(
            ExcelSqlEntry(
                number=number,
                sql_text=sql_text,
                start_row=start_row,
                end_row=end_row,
                sql_lines=tuple(sql_lines),
            )
        )
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


def _collect_sql_text(worksheet: Any, start_row: int, end_row: int) -> tuple[str, list[ExcelSqlLine]]:
    lines: list[str] = []
    sql_lines: list[ExcelSqlLine] = []
    for row_index in range(start_row, end_row + 1):
        sql_text = _cell_text(worksheet.cell(row_index, 2).value)
        if sql_text:
            note = _cell_text(worksheet.cell(row_index, 3).value)
            lines.append(sql_text)
            sql_lines.append(ExcelSqlLine(row=row_index, sql_text=sql_text, note=note))
    return "\n".join(lines).strip(), sql_lines


def _row_has_sql_content(worksheet: Any, row_index: int) -> bool:
    return bool(
        _cell_text(worksheet.cell(row_index, 2).value)
        or _cell_text(worksheet.cell(row_index, 3).value)
    )


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


def _insert_note_comments(formatted_sql: str, sql_lines: tuple[ExcelSqlLine, ...]) -> str:
    notes = [sql_line for sql_line in sql_lines if sql_line.note]
    if not notes:
        return formatted_sql

    formatted_lines = formatted_sql.splitlines()
    insertions: dict[int, list[str]] = {}
    unmatched: list[str] = []
    used_indexes: set[int] = set()
    for note in notes:
        target = _normalize_sql_fragment(note.sql_text)
        match_index: int | None = None
        for line_index, line in enumerate(formatted_lines):
            if line_index in used_indexes:
                continue
            candidate = _normalize_sql_fragment(line)
            if candidate and target and (target in candidate or candidate in target):
                match_index = line_index
                break
        if match_index is None:
            unmatched.append(_comment_line(note.note))
        else:
            used_indexes.add(match_index)
            insertions.setdefault(match_index, []).append(_comment_line(note.note))

    rendered: list[str] = []
    for line_index, line in enumerate(formatted_lines):
        rendered.append(line)
        rendered.extend(insertions.get(line_index, []))
    if unmatched:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.extend(unmatched)
    return "\n".join(rendered)


def _comment_line(note: str) -> str:
    value = note.strip()
    return value if value.startswith("--") else f"-- {value}"


def _normalize_sql_fragment(value: str) -> str:
    normalized = value.strip().rstrip(";")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.lower()
