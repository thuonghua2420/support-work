from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .constants import (
    AFTER_CURRENT_DIR,
    AFTER_NEW_DIR,
    BEFORE_CURRENT_DIR,
    BEFORE_NEW_DIR,
    COMPARE_CURRENT_FILE,
    COMPARE_DIR,
    COMPARE_NEW_FILE,
    INPUT_DIR,
    OUTPUT_DIR,
)
from .excel_writer import write_compare_workbook

Logger = Callable[[str], None]


@dataclass(frozen=True)
class WorkbookResult:
    output_path: Path
    sheet_count: int


@dataclass
class TestCaseResult:
    case_path: Path
    copied_files: int = 0
    workbooks: list[WorkbookResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ProcessSummary:
    root_path: Path
    test_cases: list[TestCaseResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def processed_count(self) -> int:
        return len(self.test_cases)


def process_root(root_path: str | Path, log: Logger | None = None) -> ProcessSummary:
    root = Path(root_path).expanduser().resolve()
    logger = log or (lambda message: None)

    if not root.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Root path is not a folder: {root}")

    summary = ProcessSummary(root_path=root)
    test_cases = discover_test_cases(root)
    if not test_cases:
        message = f"No UT* test case folders found under: {root}"
        summary.errors.append(message)
        logger(message)
        return summary

    logger(f"Found {len(test_cases)} test case folder(s).")
    for case_path in test_cases:
        result = _process_test_case(case_path, logger)
        summary.test_cases.append(result)
        summary.errors.extend(result.errors)

    logger("Done.")
    return summary


def discover_test_cases(root: Path) -> list[Path]:
    if _is_test_case_dir(root):
        return [root]

    return sorted(
        [child for child in root.iterdir() if _is_test_case_dir(child)],
        key=lambda path: path.name.lower(),
    )


def _is_test_case_dir(path: Path) -> bool:
    return path.is_dir() and path.name.upper().startswith("UT")


def _process_test_case(case_path: Path, log: Logger) -> TestCaseResult:
    result = TestCaseResult(case_path=case_path)
    log(f"[{case_path.name}] Start")

    input_dir = case_path / INPUT_DIR
    output_dir = case_path / OUTPUT_DIR
    before_new = output_dir / BEFORE_NEW_DIR
    before_current = output_dir / BEFORE_CURRENT_DIR
    after_new = output_dir / AFTER_NEW_DIR
    after_current = output_dir / AFTER_CURRENT_DIR
    compare_dir = output_dir / COMPARE_DIR

    try:
        if not input_dir.exists() or not input_dir.is_dir():
            raise FileNotFoundError(f"Missing Input folder: {input_dir}")

        for folder in (before_new, before_current, compare_dir):
            folder.mkdir(parents=True, exist_ok=True)

        copied_files = _refresh_before_folders(
            input_dir,
            before_new,
            before_current,
            after_new,
            after_current,
        )
        result.copied_files = copied_files
        log(f"[{case_path.name}] Copied {copied_files} CSV file(s) to before folders.")

        new_output = compare_dir / COMPARE_NEW_FILE
        current_output = compare_dir / COMPARE_CURRENT_FILE

        new_sheet_count = write_compare_workbook(before_new, after_new, new_output)
        current_sheet_count = write_compare_workbook(before_current, after_current, current_output)

        result.workbooks.append(WorkbookResult(new_output, new_sheet_count))
        result.workbooks.append(WorkbookResult(current_output, current_sheet_count))

        log(f"[{case_path.name}] Created {new_output.name} ({new_sheet_count} sheet(s)).")
        log(f"[{case_path.name}] Created {current_output.name} ({current_sheet_count} sheet(s)).")
    except Exception as exc:
        message = f"[{case_path.name}] ERROR: {exc}"
        result.errors.append(message)
        log(message)

    return result


def _refresh_before_folders(
    input_dir: Path,
    before_new: Path,
    before_current: Path,
    after_new: Path,
    after_current: Path,
) -> int:
    for before_dir in (before_new, before_current):
        _clear_csv_files(before_dir)

    input_csv_files = sorted(input_dir.glob("*.csv"), key=lambda path: path.name.lower())
    for source in input_csv_files:
        shutil.copy2(source, before_new / source.name)
        shutil.copy2(source, before_current / source.name)

    _prune_before_files(before_new, after_new)
    _prune_before_files(before_current, after_current)

    return len(input_csv_files)


def _clear_csv_files(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for csv_file in folder.glob("*.csv"):
        if csv_file.is_file():
            csv_file.unlink()


def _prune_before_files(before_dir: Path, after_dir: Path) -> None:
    after_names = {path.name for path in after_dir.glob("*.csv")} if after_dir.exists() else set()
    for csv_file in before_dir.glob("*.csv"):
        if csv_file.name not in after_names:
            csv_file.unlink()
