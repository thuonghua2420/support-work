from __future__ import annotations

import csv
import io
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from .compare_diagnostics import CompareDiagnosticError, compare_context, csv_location


def sort_csv_folders_by_key(
    folders: list[Path],
    keys_by_table: dict[str, tuple[str, ...]],
    log: Callable[[str], None],
    *,
    require_keys: bool = False,
    include_right_only_files: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Reorder raw CSV records without changing their values, quoting or encoding."""
    tables: dict[str, list[Path]] = {}
    unique_folders = list(dict.fromkeys(folders))
    left_tables = (
        {path.stem.casefold() for path in unique_folders[0].glob("*.csv") if path.is_file()}
        if unique_folders else set()
    )
    for folder in unique_folders:
        for path in sorted(folder.glob("*.csv")):
            if path.is_file() and (include_right_only_files or path.stem.casefold() in left_tables):
                tables.setdefault(path.stem.casefold(), []).append(path)
    plans_by_table: dict[str, tuple[tuple[str, ...], list[tuple[Path, bytes, bytes]]]] = {}
    for table, paths in tables.items():
        columns = keys_by_table.get(table)
        if not columns:
            message = f"[{table}] No key in [update_compare_keys]; extract the database key before sorting."
            if require_keys:
                raise CompareDiagnosticError(message, hint="Trích xuất key tại Database hoặc kiểm tra [update_compare_keys].",
                                             **{"Table CSV": table, "Các file CSV": "; ".join(map(str, paths))})
            log(f"[{table}] Skip ordering: no key in [update_compare_keys].")
            continue
        try:
            plans = []
            for path in paths:
                with compare_context("Đọc / kiểm tra CSV để sắp xếp", **{"File CSV": path, "Table CSV": table, "Key cấu hình": ", ".join(columns)}):
                    plans.append((path, *_ordered_csv(path, columns)))
        except ValueError as exc:
            if require_keys:
                if isinstance(exc, CompareDiagnosticError):
                    raise
                raise ValueError(f"[{table}] Cannot sort CSV by configured key: {exc}") from exc
            log(f"[{table}] Skip ordering: {exc}")
            continue
        plans_by_table[table] = (columns, plans)

    valid_keys: dict[str, tuple[str, ...]] = {}
    for table, (columns, plans) in plans_by_table.items():
        staged: list[tuple[Path, Path]] = []
        try:
            # Validate both sides before staging; replace whole files to avoid truncation.
            for path, original, ordered in plans:
                if original == ordered:
                    continue
                with compare_context("Ghi file CSV đã sắp xếp", **{"File CSV": path, "Key cấu hình": ", ".join(columns)}):
                    with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as temporary:
                        staged.append((Path(temporary.name), path))
                        temporary.write(ordered)
            for temporary, path in staged:
                with compare_context("Thay thế file CSV đã sắp xếp", **{"File CSV": path}):
                    temporary.replace(path)
            valid_keys[table] = columns
            log(f"[{table}] Ordered CSV by {', '.join(columns)}; all records retained.")
        finally:
            for temporary, _path in staged:
                temporary.unlink(missing_ok=True)
    return valid_keys


def _ordered_csv(path: Path, columns: tuple[str, ...]) -> tuple[bytes, bytes]:
    original = path.read_bytes()
    encoding = "utf-8"
    bom = b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b""
    payload = original[len(bom):]
    try:
        text = payload.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp932"
        text = payload.decode(encoding)
    lines = io.StringIO(text, newline="").readlines()
    # csv.reader tracks physical lines, including quoted multiline fields.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    records: list[tuple[list[str], str]] = []
    line_ranges: list[tuple[int, int]] = []
    start = 0
    try:
        for row in reader:
            line_ranges.append((start + 1, reader.line_num))
            records.append((row, "".join(lines[start:reader.line_num])))
            start = reader.line_num
    except csv.Error as exc:
        raise CompareDiagnosticError("CSV không hợp lệ khi sắp xếp record.", hint="Kiểm tra quote, dấu phẩy và record nhiều dòng.",
                                     **csv_location(max(0, len(records)), lines=(start + 1, max(start + 1, reader.line_num))),
                                     **{"Chi tiết kỹ thuật": str(exc)}) from exc
    if not records:
        raise CompareDiagnosticError("CSV thiếu header.", **{"File CSV": path})
    headers, header_text = records[0]
    names = [name.casefold() for name in headers]
    key_names = [column.casefold() for column in columns]
    if len(set(names)) != len(names) or len(set(key_names)) != len(key_names):
        raise CompareDiagnosticError("Header/key có tên column trùng nhau (không phân biệt hoa/thường).",
                                     **{"File CSV": path, "Header": repr(headers)[:1500], "Key cấu hình": ", ".join(columns)})
    missing = [column for column in columns if column.casefold() not in names]
    if missing:
        raise CompareDiagnosticError("Không tìm thấy column key trong header CSV.",
                                     **{"File CSV": path, "Tên column key bị thiếu": ", ".join(missing), "Header CSV": repr(headers)[:1500]})
    positions = [names.index(name) for name in key_names]
    indexed: list[tuple[tuple[str, ...], str]] = []
    seen: dict[tuple[str, ...], int] = {}
    for number, (row, raw) in enumerate(records[1:], 1):
        if len(row) != len(headers):
            column = min(len(row), len(headers)) + 1
            raise CompareDiagnosticError("Số column record không khớp header khi sắp xếp.",
                                         **csv_location(number, column, headers[column - 1] if column <= len(headers) else "[ngoài header]", line_ranges[number]),
                                         **{"Số cột header": len(headers), "Số cột record": len(row)})
        key = tuple(row[position] for position in positions)
        if any(not value.strip() for value in key) or key in seen:
            raise CompareDiagnosticError("Record có key NULL/empty hoặc duplicate key.",
                                         **csv_location(number, lines=line_ranges[number]), **{"Column key": ", ".join(columns),
                                         "Giá trị key": repr(tuple(value[:80] for value in key)), "Record key trùng trước đó": seen.get(key)})
        seen[key] = number
        indexed.append((key, raw))
    ordered = sorted(indexed, key=lambda item: item[0])
    if ordered == indexed:
        return original, original
    newline = "\r\n" if "\r\n" in text else "\n"
    blocks = [header_text, *(raw for _key, raw in ordered)]
    for index in range(len(blocks) - 1):
        if not blocks[index].endswith(("\r", "\n")):
            blocks[index] += newline
    return original, bom + "".join(blocks).encode(encoding)
