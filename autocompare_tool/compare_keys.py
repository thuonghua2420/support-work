from __future__ import annotations

import configparser
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from .app_config import default_config_path, load_app_config
from .database_io import (
    DatabaseConnectionSettings, TableNotFoundError, get_adapter, validate_connection_settings,
)
from .dbeaver_csv import read_dbeaver_csv
from .processor import discover_test_cases

SECTION = "update_compare_keys"


@dataclass(frozen=True)
class CompareKeyResult:
    update_compare_keys: dict[str, tuple[str, ...]]
    saved_count: int = 0
    removed_count: int = 0
    existing_count: int = 0
    skipped: tuple[str, ...] = ()


def _write_keys(path: Path, keys: dict[str, tuple[str, ...]]) -> None:
    original = path.read_bytes() if path.exists() else b""
    text = original.decode("utf-8")
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    section = configparser.ConfigParser(interpolation=None)
    section.add_section(SECTION)
    for table, columns in sorted(keys.items()):
        if not table or any(char in table for char in "\r\n=:[]") or table[0] in "#;":
            raise ValueError(f"Unsupported config table name: {table!r}")
        if not columns or any(not col.strip() or any(char in col for char in ",\r\n") for col in columns):
            raise ValueError(f"Unsupported key columns for {table!r}")
        section.set(SECTION, table, ", ".join(columns))
    buffer = StringIO()
    section.write(buffer)
    newline = "\r\n" if "\r\n" in text else "\n"
    replacement = buffer.getvalue().replace("\n", newline)
    # Serialize only our section; keep other settings, comments and line endings intact.
    lines = text.splitlines(keepends=True)
    start, end = None, len(lines)
    for index, line in enumerate(lines):
        match = parser.SECTCRE.match(line.strip())
        if match:
            if start is not None:
                end = index
                break
            if match.group("header") == SECTION:
                start = index
    if start is None:
        updated = text + (newline if text and not text.endswith("\n") else "") + replacement
    else:
        updated = "".join(lines[:start]) + replacement + "".join(lines[end:])
    candidate = configparser.ConfigParser(interpolation=None)
    candidate.read_string(updated)
    if dict(candidate.items(SECTION)) != {name.lower(): ", ".join(cols) for name, cols in keys.items()}:
        raise ValueError("Key names cannot be represented in the config file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(updated.encode("utf-8"))
    try:
        if (path.read_bytes() if path.exists() else b"") != original:
            raise ValueError("Config changed during key extraction. Please retry.")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def extract_compare_keys(
    root: str | Path,
    settings: DatabaseConnectionSettings,
    log: Callable[[str], None],
    *,
    config_path: Path | None = None,
    cancel: Callable[[], None] = lambda: None,
) -> CompareKeyResult:
    path = config_path if config_path is not None else default_config_path()
    config = load_app_config(path)
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Compare folder does not exist: {root}")
    tables: dict[str, list[Path]] = {}
    for case in discover_test_cases(root):
        output = case / config.folders.output_dir
        for folder in (config.folders.after_htm_dir, config.folders.after_htc_dir):
            for csv in sorted((output / folder).glob("*.csv")):
                tables.setdefault(csv.stem.casefold(), []).append(csv)
                source = case / config.folders.input_dir / csv.name
                if source.is_file() and source not in tables[csv.stem.casefold()]:
                    tables[csv.stem.casefold()].append(source)
    if not tables:
        raise ValueError("No after CSV tables found in the selected UT folder.")
    settings = validate_connection_settings(settings)
    adapter = get_adapter(settings.normalized_type)
    cancel()
    connection = adapter.connect(settings)
    found: dict[str, tuple[str, ...]] = {}
    skipped: list[str] = []
    existing_count = 0
    try:
        for table, files in sorted(tables.items()):
            cancel()
            if table in config.update_compare_keys:
                existing_count += 1
                log(f"[{table}] Keep existing configured key: {', '.join(config.update_compare_keys[table])}")
                continue
            try:
                metadata = adapter.get_table(connection, settings, files[0].stem)
                primary_key = [column.name for column in metadata.columns if column.is_primary_key]
                if not primary_key:
                    raise ValueError("table has no primary key")
                csv_keys = set()
                for csv in files:
                    cancel()
                    headers = read_dbeaver_csv(csv).headers
                    mapped = []
                    for column in primary_key:
                        matches = [header for header in headers if header.casefold() == column.casefold()]
                        if len(matches) != 1:
                            raise ValueError(f"{csv}: missing or ambiguous primary-key column {column}")
                        mapped.append(matches[0])
                    csv_keys.add(tuple(mapped))
                if len(csv_keys) != 1:
                    raise ValueError("primary-key column spelling differs across CSV files")
                found[table] = csv_keys.pop()
                log(f"[{table}] Primary key: {', '.join(found[table])}")
            except (TableNotFoundError, ValueError) as exc:
                message = f"[{table}] Skip key extraction: {exc}"
                skipped.append(message)
                log(message)
    finally:
        connection.close()
    cancel()
    # Reload before merging so unrelated keys added while querying are retained.
    keys = dict(load_app_config(path).update_compare_keys)
    additions = {table: columns for table, columns in found.items() if table not in keys}
    keys.update(additions)
    if additions:
        _write_keys(path, keys)
    log(f"Saved keys for {len(additions)} tables; kept {existing_count}; skipped {len(skipped)}.")
    return CompareKeyResult(keys, saved_count=len(additions), existing_count=existing_count, skipped=tuple(skipped))


def remove_compare_keys(log: Callable[[str], None], *, config_path: Path | None = None) -> CompareKeyResult:
    path = config_path if config_path is not None else default_config_path()
    keys = load_app_config(path).update_compare_keys
    if keys:
        _write_keys(path, {})
    log(f"Removed configured compare keys for {len(keys)} tables.")
    return CompareKeyResult({}, removed_count=len(keys))
