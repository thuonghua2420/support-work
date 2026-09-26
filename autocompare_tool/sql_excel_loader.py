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
                lines.append(_append_inline_note(sql_line.sql_text, sql_line.note))
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
    lines = value.splitlines()
    if lines and "  -- " in lines[-1]:
        sql_part, note_part = lines[-1].split("  -- ", 1)
        lines[-1] = f"{sql_part.rstrip().rstrip(';')};  -- {note_part}"
        return "\n".join(lines)
    return value if value.endswith(";") else f"{value};"


def _insert_note_comments(formatted_sql: str, sql_lines: tuple[ExcelSqlLine, ...]) -> str:
    if not any(sql_line.note for sql_line in sql_lines):
        return formatted_sql

    formatted_lines = formatted_sql.splitlines()
    formatted_tokens = _sql_tokens_with_lines(formatted_lines)
    token_cursor = 0
    last_line_index = 0
    notes_by_line: dict[int, list[str]] = {}

    # Match every column-B row in order, including rows without notes. This keeps
    # the token cursor aligned so a later column-C note cannot attach to an earlier
    # repeated SQL fragment.
    for sql_line in sql_lines:
        target_tokens = _sql_tokens(sql_line.sql_text)
        matched_indexes = _ordered_token_match(formatted_tokens, target_tokens, token_cursor)
        if matched_indexes:
            token_cursor = matched_indexes[-1] + 1
            last_line_index = formatted_tokens[matched_indexes[-1]][1]
        elif sql_line.note:
            last_line_index = _fallback_note_line(formatted_lines, sql_line.sql_text, last_line_index)
        if sql_line.note:
            notes_by_line.setdefault(last_line_index, []).append(_comment_text(sql_line.note))

    rendered: list[str] = []
    for line_index, line in enumerate(formatted_lines):
        notes = [note for note in notes_by_line.get(line_index, []) if note]
        rendered.append(f"{line.rstrip()}  -- {' | '.join(notes)}" if notes else line)
    return "\n".join(rendered)


SQL_TOKEN_PATTERN = re.compile(
    r"N?'(?:''|[^'])*'|@[A-Za-z_][A-Za-z0-9_$#]*|\[[^\]]+\]|"
    r'"(?:""|[^"])*"|`(?:``|[^`])*`|[A-Za-z_][A-Za-z0-9_$#]*|'
    r"\d+(?:\.\d+)?|<>|!=|<=|>=|:=|[-+*/%=<>,.;()]",
    re.IGNORECASE,
)


def _sql_tokens(value: str) -> list[str]:
    return [match.group(0).casefold() for match in SQL_TOKEN_PATTERN.finditer(value)]


def _sql_tokens_with_lines(lines: list[str]) -> list[tuple[str, int]]:
    return [
        (token, line_index)
        for line_index, line in enumerate(lines)
        for token in _sql_tokens(line)
    ]


def _ordered_token_match(
    formatted_tokens: list[tuple[str, int]],
    target_tokens: list[str],
    start_index: int,
) -> list[int]:
    if not target_tokens:
        return []
    matched: list[int] = []
    cursor = max(0, start_index)
    for target in target_tokens:
        match_index = next(
            (index for index in range(cursor, len(formatted_tokens)) if formatted_tokens[index][0] == target),
            None,
        )
        if match_index is None:
            return []
        matched.append(match_index)
        cursor = match_index + 1
    return matched


def _fallback_note_line(lines: list[str], sql_text: str, start_line: int) -> int:
    target = _normalize_sql_fragment(sql_text)
    for line_index in range(max(0, start_line), len(lines)):
        candidate = _normalize_sql_fragment(lines[line_index])
        if candidate and target and (target in candidate or candidate in target):
            return line_index
    for line_index in range(len(lines) - 1, -1, -1):
        if lines[line_index].strip():
            return line_index
    return 0


def _append_inline_note(sql_text: str, note: str) -> str:
    if not note:
        return sql_text
    lines = sql_text.splitlines() or [sql_text]
    target_index = next((index for index in range(len(lines) - 1, -1, -1) if lines[index].strip()), len(lines) - 1)
    lines[target_index] = f"{lines[target_index].rstrip()}  -- {_comment_text(note)}"
    return "\n".join(lines)


def _comment_text(note: str) -> str:
    value = note.strip()
    return value[2:].lstrip() if value.startswith("--") else value


def _normalize_sql_fragment(value: str) -> str:
    normalized = value.strip().rstrip(";")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.lower()
