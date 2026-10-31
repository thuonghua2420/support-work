from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .compare_diagnostics import CompareDiagnosticError, csv_location


@dataclass(frozen=True)
class DbeaverCsv:
    headers: list[str]
    rows: list[list[str | None]]
    line_ranges: list[tuple[int, int]] = field(default_factory=list, compare=False)


@dataclass(frozen=True)
class CsvCell:
    value: str | None
    quoted: bool


def read_dbeaver_csv(path: Path, *, strict: bool = False) -> DbeaverCsv:
    text = _read_text(path)
    line_ranges: list[tuple[int, int]] = []
    parsed_rows = _parse_csv_cells(text, strict=strict, line_ranges=line_ranges if strict else None)
    if not parsed_rows:
        return DbeaverCsv(headers=[], rows=[])

    headers = [cell.value or "" for cell in parsed_rows[0]]
    if strict:
        positions: dict[str, int] = {}
        for index, name in enumerate(headers, 1):
            if not name or name in positions:
                raise CompareDiagnosticError(
                    "Header CSV trống hoặc trùng tên column.",
                    hint="Mỗi column phải có tên riêng; header trùng tên sẽ làm mất giá trị khi ánh xạ record.",
                    **csv_location(0, index, name, line_ranges[0]),
                    **{"Cột trùng trước đó": positions.get(name)},
                )
            positions[name] = index
        for record, row in enumerate(parsed_rows[1:], 1):
            if len(row) != len(headers):
                column = min(len(row), len(headers)) + 1
                raise CompareDiagnosticError(
                    "Số lượng cột trong record CSV không khớp header.",
                    hint="Kiểm tra dấu phẩy, dấu quote và newline trong record; giá trị chứa dấu phẩy/newline cần nằm trong quote.",
                    **csv_location(record, column, headers[column - 1] if column <= len(headers) else "[ngoài header]", line_ranges[record]),
                    **{"Số cột header": len(headers), "Số cột record": len(row), "Chênh lệch": len(row) - len(headers)},
                )
    max_columns = max(len(row) for row in parsed_rows)
    while len(headers) < max_columns:
        headers.append(f"Column{len(headers) + 1}")

    rows: list[list[str | None]] = []
    for parsed_row in parsed_rows[1:]:
        row_values = [cell.value for cell in parsed_row]
        while len(row_values) < len(headers):
            row_values.append(None)
        rows.append(row_values[: len(headers)])

    return DbeaverCsv(headers=headers, rows=rows, line_ranges=line_ranges)


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


class TypedDbeaverCsvRowWriter:
    """Incremental writer for typed DBeaver-style CSV rows."""

    def __init__(self, path: Path, headers: list[str], quote_columns: list[bool]) -> None:
        if len(headers) != len(quote_columns):
            raise ValueError("Sá»‘ lÆ°á»£ng header vÃ  cáº¥u hÃ¬nh quote column khÃ´ng khá»›p.")
        self.path = path
        self.headers = headers
        self.quote_columns = quote_columns
        self.row_count = 0
        self._file = None

    def __enter__(self) -> "TypedDbeaverCsvRowWriter":
        self.open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def open(self) -> None:
        if self._file is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8", newline="")
        if self.headers:
            self._file.write(",".join(_format_header(header) for header in self.headers))
            self._file.write("\r\n")

    def write_rows(self, rows: Iterable[Sequence[str | None]]) -> int:
        self.open()
        if self._file is None or not self.headers:
            return 0
        written = 0
        for row in rows:
            cells: list[str] = []
            for index in range(len(self.headers)):
                value = row[index] if index < len(row) else None
                cells.append(_format_typed_data_cell(value, self.quote_columns[index]))
            self._file.write(",".join(cells))
            self._file.write("\r\n")
            self.row_count += 1
            written += 1
        return written

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def _read_text(path: Path) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            # newline="" is intentional: universal-newline translation would
            # collapse CRLF inside quoted values to LF before comparison.
            with path.open("r", encoding=encoding, newline="") as file:
                return file.read()
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return ""


def _parse_csv_cells(text: str, *, strict: bool = False,
                     line_ranges: list[tuple[int, int]] | None = None) -> list[list[CsvCell]]:
    rows: list[list[CsvCell]] = []
    row: list[CsvCell] = []
    field_chars: list[str] = []
    in_quotes = False
    quoted = False
    at_field_start = True
    row_has_content = False
    physical_line = 1
    row_start = 1
    after_quote = False

    def commit_field() -> None:
        nonlocal field_chars, quoted, at_field_start, row_has_content, after_quote
        raw_value = "".join(field_chars)
        value: str | None = raw_value
        if not quoted and raw_value == "":
            value = None
        row.append(CsvCell(value=value, quoted=quoted))
        field_chars = []
        quoted = False
        at_field_start = True
        after_quote = False
        row_has_content = True

    def commit_row() -> None:
        nonlocal row, row_has_content
        rows.append(row)
        if line_ranges is not None:
            line_ranges.append((row_start, physical_line))
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
                after_quote = True
            else:
                field_chars.append(char)
                if char == "\r" or (char == "\n" and (index == 0 or text[index - 1] != "\r")):
                    physical_line += 1
            at_field_start = False
            index += 1
            continue

        if strict and after_quote and char not in {",", "\r", "\n"}:
            raise CompareDiagnosticError(
                "CSV có ký tự không hợp lệ sau dấu quote đóng.",
                hint="Sau quote đóng phải là dấu phẩy hoặc kết thúc record. Quote bên trong giá trị phải viết thành hai quote liên tiếp.",
                **csv_location(len(rows), len(row) + 1, _parsed_header(rows, len(row)), (row_start, physical_line)),
                **{"Ký tự": repr(char)},
            )

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
            physical_line += 1
            row_start = physical_line
            continue

        field_chars.append(char)
        at_field_start = False
        row_has_content = True
        index += 1

    if strict and in_quotes:
        raise CompareDiagnosticError(
            "CSV thiếu dấu quote đóng ở cuối file.",
            hint="Kiểm tra ô chứa newline hoặc quote; quote chưa đóng có thể gộp nhiều dòng thành một record rất lớn.",
            **csv_location(len(rows), len(row) + 1, _parsed_header(rows, len(row)), (row_start, physical_line)),
        )
    if field_chars or quoted or row or row_has_content:
        commit_field()
        commit_row()

    return rows


def _parsed_header(rows: list[list[CsvCell]], index: int) -> str | None:
    return str(rows[0][index].value or "") if rows and index < len(rows[0]) else None


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
