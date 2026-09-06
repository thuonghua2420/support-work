from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from .dbeaver_csv import DbeaverCsv, read_dbeaver_csv, write_dbeaver_csv


def _index_rows(table: DbeaverCsv, columns: tuple[str, ...], path: Path) -> dict[tuple[str, ...], int]:
    if not columns or len(set(columns)) != len(columns):
        raise ValueError(f"{path.name}: invalid update key columns.")
    if len(set(table.headers)) != len(table.headers):
        raise ValueError(f"{path.name}: duplicate CSV headers.")
    missing = [column for column in columns if column not in table.headers]
    if missing:
        raise ValueError(f"{path.name}: missing key columns: {', '.join(missing)}.")
    positions = [table.headers.index(column) for column in columns]
    indexed: dict[tuple[str, ...], int] = {}
    for number, row in enumerate(table.rows, 1):
        key = tuple(row[position] for position in positions)
        if any(value is None or not value.strip() for value in key):
            raise ValueError(f"{path}: record {number} has a NULL/empty update key.")
        if key in indexed:
            raise ValueError(f"{path}: duplicate update key at records {indexed[key]} and {number}.")
        indexed[key] = number
    return indexed


def filter_update_before_folder(
    before_dir: Path,
    after_dir: Path,
    keys_by_table: dict[str, tuple[str, ...]],
    log: Callable[[str], None],
    *,
    strict: bool = True,
) -> set[Path]:
    """Filter before CSVs in after order and return paths with validated alignment."""
    if not after_dir.is_dir():
        if strict:
            raise ValueError(f"Missing after folder: {after_dir}")
        log(f"[{before_dir.name}] Skip update-scope filter: missing after folder {after_dir}.")
        return set()
    after_files = sorted(after_dir.glob("*.csv"), key=lambda path: path.name.casefold())
    if not after_files:
        if strict:
            raise ValueError(f"No after CSV files: {after_dir}")
        log(f"[{before_dir.name}] Skip update-scope filter: no after CSV files in {after_dir}.")
        return set()
    plans = []
    for after_path in after_files:
        try:
            plans.append(_build_filter_plan(before_dir, after_path, keys_by_table))
        except ValueError as exc:
            if strict:
                raise
            log(f"[{before_dir.name}/{after_path.name}] Skip update-scope filter: {exc}")

    # Stage all writes first; replace each CSV atomically to avoid truncated inputs.
    staged: list[tuple[Path, Path]] = []
    try:
        for path, before, columns, kept, removed in plans:
            with NamedTemporaryFile(dir=before_dir, suffix=".tmp", delete=False) as temporary:
                temporary_path = Path(temporary.name)
            staged.append((temporary_path, path))
            write_dbeaver_csv(temporary_path, before.headers, [before.rows[number - 1] for number in kept])
        for temporary_path, path in staged:
            temporary_path.replace(path)
        for path, before, columns, kept, removed in plans:
            log(
                f"[{before_dir.name}/{path.name}] Update keys: {', '.join(columns)}; "
                f"before={len(before.rows)}, kept={len(kept)}, removed={len(removed)}; "
                f"original records in after order={kept}; excluded original records={removed}"
            )
    finally:
        for temporary_path, _path in staged:
            temporary_path.unlink(missing_ok=True)
    return {path for path, _before, _columns, _kept, _removed in plans}


def _build_filter_plan(
    before_dir: Path,
    after_path: Path,
    keys_by_table: dict[str, tuple[str, ...]],
) -> tuple[Path, DbeaverCsv, tuple[str, ...], list[int], list[int]]:
    before_path = before_dir / after_path.name
    if not before_path.is_file():
        raise ValueError("missing before CSV; compare will use an empty before side for this file.")
    columns = keys_by_table.get(after_path.stem.casefold())
    if not columns:
        raise ValueError(
            "missing stable key config in [update_compare_keys]; "
            "before CSV is kept unchanged to avoid removing the wrong record."
        )
    before = read_dbeaver_csv(before_path)
    after = read_dbeaver_csv(after_path)
    if not after.rows:
        raise ValueError("after is empty; before CSV is kept unchanged.")
    before_index = _index_rows(before, columns, before_path)
    after_index = _index_rows(after, columns, after_path)
    missing = [number for key, number in after_index.items() if key not in before_index]
    if missing:
        raise ValueError(
            f"after records without before mapping: {missing}; "
            "before CSV is kept unchanged to avoid removing the wrong record."
        )
    kept = [before_index[key] for key in after_index]
    selected = set(kept)
    removed = [number for number in range(1, len(before.rows) + 1) if number not in selected]
    return before_path, before, columns, kept, removed
