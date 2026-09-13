from __future__ import annotations

import csv
import io
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable


def sort_csv_folders_by_key(
    folders: list[Path],
    keys_by_table: dict[str, tuple[str, ...]],
    log: Callable[[str], None],
) -> dict[str, tuple[str, ...]]:
    """Reorder raw CSV records without changing their values, quoting or encoding."""
    tables: dict[str, list[Path]] = {}
    for folder in dict.fromkeys(folders):
        for path in sorted(folder.glob("*.csv")):
            if path.is_file():
                tables.setdefault(path.stem.casefold(), []).append(path)
    valid_keys: dict[str, tuple[str, ...]] = {}
    for table, paths in tables.items():
        columns = keys_by_table.get(table)
        if not columns:
            log(f"[{table}] Skip ordering: no key in [update_compare_keys].")
            continue
        try:
            plans = [(path, *_ordered_csv(path, columns)) for path in paths]
        except ValueError as exc:
            log(f"[{table}] Skip ordering: {exc}")
            continue
        staged: list[tuple[Path, Path]] = []
        try:
            # Validate both sides before staging; replace whole files to avoid truncation.
            for path, original, ordered in plans:
                if original == ordered:
                    continue
                with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as temporary:
                    staged.append((Path(temporary.name), path))
                    temporary.write(ordered)
            for temporary, path in staged:
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
    start = 0
    try:
        for row in reader:
            records.append((row, "".join(lines[start:reader.line_num])))
            start = reader.line_num
    except csv.Error as exc:
        raise ValueError(f"{path}: invalid CSV: {exc}") from exc
    if not records:
        raise ValueError(f"{path}: missing CSV header.")
    headers, header_text = records[0]
    names = [name.casefold() for name in headers]
    key_names = [column.casefold() for column in columns]
    if len(set(names)) != len(names) or len(set(key_names)) != len(key_names):
        raise ValueError(f"{path}: duplicate header/key columns.")
    missing = [column for column in columns if column.casefold() not in names]
    if missing:
        raise ValueError(f"{path}: missing key columns: {', '.join(missing)}.")
    positions = [names.index(name) for name in key_names]
    indexed: list[tuple[tuple[str, ...], str]] = []
    seen: set[tuple[str, ...]] = set()
    for number, (row, raw) in enumerate(records[1:], 1):
        if len(row) != len(headers):
            raise ValueError(f"{path}: record {number} has an unexpected column count.")
        key = tuple(row[position] for position in positions)
        if any(not value.strip() for value in key) or key in seen:
            raise ValueError(f"{path}: record {number} has a NULL/empty or duplicate key.")
        seen.add(key)
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
