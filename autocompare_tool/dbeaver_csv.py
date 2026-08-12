from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class DbeaverCsv:
    headers: list[str]
    rows: list[list[str | None]]


@dataclass(frozen=True)
class CsvCell:
    value: str | None
    quoted: bool


def read_dbeaver_csv(path: Path) -> DbeaverCsv:
    text = _read_text(path)
    parsed_rows = _parse_csv_cells(text)
    if not parsed_rows:
        return DbeaverCsv(headers=[], rows=[])

    headers = [cell.value or "" for cell in parsed_rows[0]]
    max_columns = max(len(row) for row in parsed_rows)
    while len(headers) < max_columns:
        headers.append(f"Column{len(headers) + 1}")

    rows: list[list[str | None]] = []
    for parsed_row in parsed_rows[1:]:
        row_values = [cell.value for cell in parsed_row]
        while len(row_values) < len(headers):
            row_values.append(None)
        rows.append(row_values[: len(headers)])

    return DbeaverCsv(headers=headers, rows=rows)


def write_dbeaver_csv(path: Path, headers: list[str], rows: list[list[str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        if not headers:
            return
        file.write(",".join(_format_header(header) for header in headers))
        file.write("\r\n")
        for row in rows:
            file.write(",".join(_format_data_cell(value) for value in row))
            file.write("\r\n")


def write_typed_dbeaver_csv(
    path: Path,
    headers: list[str],
    rows: list[list[str | None]],
    quote_columns: list[bool],
) -> None:
    if len(headers) != len(quote_columns):
        raise ValueError("Số lượng header và cấu hình quote column không khớp.")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        if not headers:
            return
        file.write(",".join(_format_header(header) for header in headers))
        file.write("\r\n")
        for row in rows:
            cells: list[str] = []
            for index, value in enumerate(row):
                should_quote = quote_columns[index] if index < len(quote_columns) else True
                cells.append(_format_typed_data_cell(value, should_quote))
            file.write(",".join(cells))
            file.write("\r\n")


def write_typed_dbeaver_csv_rows(
    path: Path,
    headers: list[str],
    rows: Iterable[Sequence[str | None]],
    quote_columns: list[bool],
) -> int:
    """Stream typed rows to disk and return the number of rows written."""
    if len(headers) != len(quote_columns):
        raise ValueError("Số lượng header và cấu hình quote column không khớp.")

    path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with path.open("w", encoding="utf-8", newline="") as file:
        if not headers:
            return 0
        file.write(",".join(_format_header(header) for header in headers))
        file.write("\r\n")
        for row in rows:
            cells: list[str] = []
            for index in range(len(headers)):
                value = row[index] if index < len(row) else None
                should_quote = quote_columns[index]
                cells.append(_format_typed_data_cell(value, should_quote))
            file.write(",".join(cells))
            file.write("\r\n")
            row_count += 1
    return row_count


def _read_text(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return ""


def _parse_csv_cells(text: str) -> list[list[CsvCell]]:
    rows: list[list[CsvCell]] = []
    row: list[CsvCell] = []
    field_chars: list[str] = []
    in_quotes = False
    quoted = False
    at_field_start = True
    row_has_content = False

    def commit_field() -> None:
        nonlocal field_chars, quoted, at_field_start, row_has_content
        raw_value = "".join(field_chars)
        value: str | None = raw_value
        if not quoted and raw_value == "":
            value = None
        row.append(CsvCell(value=value, quoted=quoted))
        field_chars = []
        quoted = False
        at_field_start = True
        row_has_content = True

    def commit_row() -> None:
        nonlocal row, row_has_content
        rows.append(row)
        row = []
        row_has_content = False

    index = 0
    while index < len(text):
        char = text[index]

        if in_quotes:
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    field_chars.append('"')
                    index += 2
                    continue
                in_quotes = False
            else:
                field_chars.append(char)
            at_field_start = False
            index += 1
            continue

        if at_field_start and char == '"':
            quoted = True
            in_quotes = True
            at_field_start = False
            index += 1
            continue

        if char == ",":
            commit_field()
            index += 1
            continue

        if char == "\r" or char == "\n":
            commit_field()
            commit_row()
            if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 2
            else:
                index += 1
            continue

        field_chars.append(char)
        at_field_start = False
        row_has_content = True
        index += 1

    if field_chars or quoted or row or row_has_content:
        commit_field()
        commit_row()

    return rows


def _format_header(value: str) -> str:
    if value == "":
        return '""'
    if any(char in value for char in [",", '"', "\r", "\n"]):
        return _quote(value)
    return value


def _format_data_cell(value: str | None) -> str:
    if value is None:
        return ""
    return _quote(value)


def _format_typed_data_cell(value: str | None, should_quote: bool) -> str:
    if value is None:
        return ""
    if value == "":
        return '""'
    if should_quote or any(char in value for char in [",", '"', "\r", "\n"]):
        return _quote(value)
    return value


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
