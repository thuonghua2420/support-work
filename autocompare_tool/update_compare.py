from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from .dbeaver_csv import DbeaverCsv, read_dbeaver_csv, write_dbeaver_csv


@dataclass(frozen=True)
class UpdateFilterPlan:
    before_path: Path
    after_path: Path
    before: DbeaverCsv
    after: DbeaverCsv
    columns: tuple[str, ...]
    kept_before: list[int]
    kept_after: list[int]
    removed_before: list[int]
    removed_after: list[int]


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
    """Keep only stable keys shared by before/after and return aligned before paths."""
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
        for plan in plans:
            with NamedTemporaryFile(dir=before_dir, suffix=".tmp", delete=False) as temporary:
                before_temporary = Path(temporary.name)
            staged.append((before_temporary, plan.before_path))
            write_dbeaver_csv(
                before_temporary,
                plan.before.headers,
                [plan.before.rows[number - 1] for number in plan.kept_before],
            )
            if plan.removed_after:
                with NamedTemporaryFile(dir=after_dir, suffix=".tmp", delete=False) as temporary:
                    after_temporary = Path(temporary.name)
                staged.append((after_temporary, plan.after_path))
                write_dbeaver_csv(
                    after_temporary,
                    plan.after.headers,
                    [plan.after.rows[number - 1] for number in plan.kept_after],
                )
        for temporary_path, path in staged:
            temporary_path.replace(path)
        for plan in plans:
            log(
                f"[{before_dir.name}/{plan.before_path.name}] Update keys: {', '.join(plan.columns)}; "
                f"shared={len(plan.kept_before)}; "
                f"before={len(plan.before.rows)}, removed delete records={plan.removed_before}; "
                f"after={len(plan.after.rows)}, removed insert records={plan.removed_after}; "
                f"before records in after order={plan.kept_before}"
            )
    finally:
        for temporary_path, _path in staged:
            temporary_path.unlink(missing_ok=True)
    return {plan.before_path for plan in plans}


def _build_filter_plan(
    before_dir: Path,
    after_path: Path,
    keys_by_table: dict[str, tuple[str, ...]],
) -> UpdateFilterPlan:
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
    before_index = _index_rows(before, columns, before_path)
    after_index = _index_rows(after, columns, after_path)
    shared_keys = [key for key in after_index if key in before_index]
    kept_before = [before_index[key] for key in shared_keys]
    kept_after = [after_index[key] for key in shared_keys]
    selected_before = set(kept_before)
    selected_after = set(kept_after)
    removed_before = [number for number in range(1, len(before.rows) + 1) if number not in selected_before]
    removed_after = [number for number in range(1, len(after.rows) + 1) if number not in selected_after]
    return UpdateFilterPlan(
        before_path=before_path,
        after_path=after_path,
        before=before,
        after=after,
        columns=columns,
        kept_before=kept_before,
        kept_after=kept_after,
        removed_before=removed_before,
        removed_after=removed_after,
    )
