#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import filecmp
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


# =========================
# Folder name configuration
# =========================
ROOT_FOLDER_PREFIX = "UT"

SOURCE_INPUT_FOLDER_NAME = "input"
SOURCE_OUTPUT_FOLDER_NAME = "output"

TARGET_INPUT_FOLDER_NAME = "\u5165\u529b"
TARGET_OUTPUT_FOLDER_NAME = "\u51fa\u529b"
TARGET_OUTPUT_SYSTEM_FOLDER_NAME = "\u73fe\u5728\u306e\u30b7\u30b9\u30c6\u30e0\u4ee5\u964d"


# =================
# Log configuration
# =================
LOG_FOLDER_NAME = "copy_logs"
LOG_FILE_PREFIX = "copy_compare_log"

# 0 means no limit. Set this to a positive number if the log becomes too large.
MAX_DIFF_DETAILS_PER_CSV = 0


# ======================
# CSV read configuration
# ======================
CSV_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "cp932",
    "shift_jis",
    "mbcs",
)


class Logger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.lines: List[str] = []

    def add(self, message: str = "") -> None:
        self.lines.append(message)

    def section(self, title: str) -> None:
        self.add("")
        self.add("=" * 100)
        self.add(title)
        self.add("=" * 100)

    def write(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def normalize_folder_name(name: str) -> str:
    return name.casefold()


def find_child_dir(parent: Path, folder_name: str) -> Optional[Path]:
    expected = normalize_folder_name(folder_name)
    if not parent.is_dir():
        return None

    for child in parent.iterdir():
        if child.is_dir() and normalize_folder_name(child.name) == expected:
            return child

    return None


def iter_root_folders(path1: Path) -> Iterable[Path]:
    expected_prefix = normalize_folder_name(ROOT_FOLDER_PREFIX)
    for child in sorted(path1.iterdir(), key=lambda item: item.name.casefold()):
        if child.is_dir() and normalize_folder_name(child.name).startswith(expected_prefix):
            yield child


def iter_files_recursive(source_dir: Path) -> Iterable[Path]:
    for item in sorted(source_dir.rglob("*"), key=lambda file_path: str(file_path).casefold()):
        if item.is_file():
            yield item


def is_csv_file(path: Path) -> bool:
    return path.suffix.casefold() == ".csv"


def read_csv_rows(path: Path) -> Tuple[List[List[str]], str]:
    last_error: Optional[Exception] = None

    for encoding in CSV_ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as file:
                return list(csv.reader(file)), encoding
        except UnicodeDecodeError as error:
            last_error = error
        except LookupError as error:
            last_error = error

    raise UnicodeError(f"Cannot read CSV with configured encodings: {path}. Last error: {last_error}")


def read_text(path: Path, encoding: str) -> str:
    with path.open("r", encoding=encoding, newline="") as file:
        return file.read()


def read_csv_raw_records(path: Path, encoding: str) -> List[List[str]]:
    text = read_text(path, encoding)
    records: List[List[str]] = []
    row: List[str] = []
    field: List[str] = []
    in_quotes = False
    record_has_data = False
    last_char_was_delimiter = False

    i = 0
    while i < len(text):
        char = text[i]

        if char == '"':
            field.append(char)
            record_has_data = True
            last_char_was_delimiter = False

            if in_quotes:
                if i + 1 < len(text) and text[i + 1] == '"':
                    i += 1
                    field.append(text[i])
                else:
                    in_quotes = False
            elif "".join(field[:-1]).strip() == "":
                in_quotes = True

        elif char == "," and not in_quotes:
            row.append("".join(field))
            field = []
            record_has_data = True
            last_char_was_delimiter = True

        elif char in ("\r", "\n") and not in_quotes:
            row.append("".join(field))
            records.append(row)
            row = []
            field = []
            record_has_data = False
            last_char_was_delimiter = False

            if char == "\r" and i + 1 < len(text) and text[i + 1] == "\n":
                i += 1

        else:
            field.append(char)
            record_has_data = True
            last_char_was_delimiter = False

        i += 1

    if record_has_data or row or last_char_was_delimiter:
        row.append("".join(field))
        records.append(row)

    return records


def format_cell(value: Optional[str]) -> str:
    if value is None:
        return "<MISSING>"
    return repr(value)


def log_raw_csv_field_differences(
    source_file: Path,
    target_file: Path,
    source_encoding: str,
    target_encoding: str,
    source_rows: List[List[str]],
    target_rows: List[List[str]],
    logger: Logger,
) -> None:
    try:
        source_raw_rows = read_csv_raw_records(source_file, source_encoding)
        target_raw_rows = read_csv_raw_records(target_file, target_encoding)
    except Exception as error:
        logger.add(f"[CSV RAW COMPARE ERROR] Cannot compare raw CSV fields: {error}")
        return

    max_rows = max(len(source_raw_rows), len(target_raw_rows))
    diff_count = 0
    same_row_count = 0
    limit = MAX_DIFF_DETAILS_PER_CSV
    limit_reached = False

    for row_index in range(max_rows):
        source_raw_row = source_raw_rows[row_index] if row_index < len(source_raw_rows) else None
        target_raw_row = target_raw_rows[row_index] if row_index < len(target_raw_rows) else None

        if source_raw_row == target_raw_row:
            same_row_count += 1
            continue

        display_row = row_index + 1

        if source_raw_row is None:
            logger.add(f"[ROW FORMAT DIFFERENT] Row {display_row}: raw row exists only in target.")
            if not target_raw_row:
                diff_count += 1
                if limit and diff_count > limit:
                    limit_reached = True
                    break
                logger.add(f"[COLUMN FORMAT DIFF] Row {display_row}: source_raw=<MISSING> | target_raw=[]")
            else:
                for col_index, target_raw_value in enumerate(target_raw_row):
                    diff_count += 1
                    if limit and diff_count > limit:
                        limit_reached = True
                        break

                    target_value = (
                        target_rows[row_index][col_index]
                        if row_index < len(target_rows) and col_index < len(target_rows[row_index])
                        else None
                    )
                    display_col = col_index + 1
                    logger.add(
                        f"[COLUMN FORMAT DIFF] Row {display_row}, Column {display_col}: "
                        f"source_raw=<MISSING> | "
                        f"target_raw={format_cell(target_raw_value)} | "
                        f"source_value=<MISSING> | "
                        f"target_value={format_cell(target_value)}"
                    )

            if limit_reached:
                break
            continue

        if target_raw_row is None:
            logger.add(f"[ROW FORMAT DIFFERENT] Row {display_row}: raw row exists only in source.")
            if not source_raw_row:
                diff_count += 1
                if limit and diff_count > limit:
                    limit_reached = True
                    break
                logger.add(f"[COLUMN FORMAT DIFF] Row {display_row}: source_raw=[] | target_raw=<MISSING>")
            else:
                for col_index, source_raw_value in enumerate(source_raw_row):
                    diff_count += 1
                    if limit and diff_count > limit:
                        limit_reached = True
                        break

                    source_value = (
                        source_rows[row_index][col_index]
                        if row_index < len(source_rows) and col_index < len(source_rows[row_index])
                        else None
                    )
                    display_col = col_index + 1
                    logger.add(
                        f"[COLUMN FORMAT DIFF] Row {display_row}, Column {display_col}: "
                        f"source_raw={format_cell(source_raw_value)} | "
                        f"target_raw=<MISSING> | "
                        f"source_value={format_cell(source_value)} | "
                        f"target_value=<MISSING>"
                    )

            if limit_reached:
                break
            continue

        logger.add(f"[ROW FORMAT DIFFERENT] Row {display_row}")
        max_cols = max(len(source_raw_row), len(target_raw_row))
        for col_index in range(max_cols):
            source_raw_value = source_raw_row[col_index] if col_index < len(source_raw_row) else None
            target_raw_value = target_raw_row[col_index] if col_index < len(target_raw_row) else None

            if source_raw_value == target_raw_value:
                continue

            diff_count += 1
            if limit and diff_count > limit:
                limit_reached = True
                break

            source_value = (
                source_rows[row_index][col_index]
                if row_index < len(source_rows) and col_index < len(source_rows[row_index])
                else None
            )
            target_value = (
                target_rows[row_index][col_index]
                if row_index < len(target_rows) and col_index < len(target_rows[row_index])
                else None
            )

            display_col = col_index + 1
            logger.add(
                f"[COLUMN FORMAT DIFF] Row {display_row}, Column {display_col}: "
                f"source_raw={format_cell(source_raw_value)} | "
                f"target_raw={format_cell(target_raw_value)} | "
                f"source_value={format_cell(source_value)} | "
                f"target_value={format_cell(target_value)}"
            )

        if limit_reached:
            break

    logger.add(f"[CSV RAW DIFFERENT] Same rows: {same_row_count}, different columns: {diff_count}")
    if limit_reached:
        logger.add(f"[CSV RAW DIFFERENT] Diff detail limit reached: {MAX_DIFF_DETAILS_PER_CSV}")


def compare_csv_files(source_file: Path, target_file: Path, logger: Logger) -> bool:
    try:
        source_rows, source_encoding = read_csv_rows(source_file)
        target_rows, target_encoding = read_csv_rows(target_file)
    except Exception as error:
        logger.add(f"[CSV COMPARE ERROR] Cannot compare CSV before overwrite: {error}")
        return True

    if source_rows == target_rows:
        try:
            if filecmp.cmp(source_file, target_file, shallow=False):
                return False
        except OSError as error:
            logger.add(f"[CSV RAW COMPARE ERROR] Could not compare raw files: {error}")

        logger.add(f"[CSV FORMAT DIFFERENT] Parsed CSV values are same, but raw file content differs.")
        logger.add(f"[CSV COMPARE] Source: {source_file}")
        logger.add(f"[CSV COMPARE] Target: {target_file}")
        logger.add(f"Source encoding: {source_encoding}")
        logger.add(f"Target encoding: {target_encoding}")
        logger.add(f"Source rows: {len(source_rows)}")
        logger.add(f"Target rows: {len(target_rows)}")
        log_raw_csv_field_differences(
            source_file,
            target_file,
            source_encoding,
            target_encoding,
            source_rows,
            target_rows,
            logger,
        )
        return True

    logger.add(f"[CSV COMPARE] Source: {source_file}")
    logger.add(f"[CSV COMPARE] Target: {target_file}")
    logger.add(f"Source encoding: {source_encoding}")
    logger.add(f"Target encoding: {target_encoding}")
    logger.add(f"Source rows: {len(source_rows)}")
    logger.add(f"Target rows: {len(target_rows)}")

    max_rows = max(len(source_rows), len(target_rows))
    diff_count = 0
    same_row_count = 0
    limit = MAX_DIFF_DETAILS_PER_CSV
    limit_reached = False

    for row_index in range(max_rows):
        source_row = source_rows[row_index] if row_index < len(source_rows) else None
        target_row = target_rows[row_index] if row_index < len(target_rows) else None
        display_row = row_index + 1

        if source_row == target_row:
            same_row_count += 1
            continue

        if source_row is None:
            logger.add(f"[ROW DIFFERENT] Row {display_row}: row exists only in target.")
            if not target_row:
                diff_count += 1
                if limit and diff_count > limit:
                    limit_reached = True
                    break
                logger.add(f"[COLUMN DIFF] Row {display_row}: source=<MISSING> | target=[]")
            else:
                for col_index, target_value in enumerate(target_row):
                    diff_count += 1
                    if limit and diff_count > limit:
                        limit_reached = True
                        break

                    display_col = col_index + 1
                    logger.add(
                        f"[COLUMN DIFF] Row {display_row}, Column {display_col}: "
                        f"source=<MISSING> | target={format_cell(target_value)}"
                    )

            if limit_reached:
                break
            continue

        if target_row is None:
            logger.add(f"[ROW DIFFERENT] Row {display_row}: row exists only in source.")
            if not source_row:
                diff_count += 1
                if limit and diff_count > limit:
                    limit_reached = True
                    break
                logger.add(f"[COLUMN DIFF] Row {display_row}: source=[] | target=<MISSING>")
            else:
                for col_index, source_value in enumerate(source_row):
                    diff_count += 1
                    if limit and diff_count > limit:
                        limit_reached = True
                        break

                    display_col = col_index + 1
                    logger.add(
                        f"[COLUMN DIFF] Row {display_row}, Column {display_col}: "
                        f"source={format_cell(source_value)} | target=<MISSING>"
                    )

            if limit_reached:
                break
            continue

        logger.add(f"[ROW DIFFERENT] Row {display_row}")
        max_cols = max(len(source_row), len(target_row))
        for col_index in range(max_cols):
            source_value = source_row[col_index] if col_index < len(source_row) else None
            target_value = target_row[col_index] if col_index < len(target_row) else None

            if source_value == target_value:
                continue

            diff_count += 1
            if limit and diff_count > limit:
                limit_reached = True
                break

            display_col = col_index + 1
            logger.add(
                f"[COLUMN DIFF] Row {display_row}, Column {display_col}: "
                f"source={format_cell(source_value)} | target={format_cell(target_value)}"
            )

        if limit_reached:
            break

    logger.add(f"[CSV DIFFERENT] Same rows: {same_row_count}, difference entries: {diff_count}")
    if limit_reached:
        logger.add(f"[CSV DIFFERENT] Diff detail limit reached: {MAX_DIFF_DETAILS_PER_CSV}")
    return True


def copy_file_with_log(source_file: Path, target_file: Path, logger: Logger) -> None:
    target_file.parent.mkdir(parents=True, exist_ok=True)

    if not target_file.exists():
        logger.add(f"[NEW FILE] Copy new file: {source_file} -> {target_file}")
        shutil.copy2(source_file, target_file)
        return

    if target_file.is_dir():
        logger.add(f"[SKIP] Target path is a directory, cannot overwrite with file: {target_file}")
        return

    should_log_overwrite = True

    if is_csv_file(source_file) and is_csv_file(target_file):
        should_log_overwrite = compare_csv_files(source_file, target_file, logger)
    else:
        try:
            if filecmp.cmp(source_file, target_file, shallow=False):
                should_log_overwrite = False
            else:
                logger.add(f"[OVERWRITE NON-CSV] Existing file differs and will be overwritten: {target_file}")
        except OSError as error:
            logger.add(f"[OVERWRITE NON-CSV] Could not compare non-CSV file: {target_file}. Error: {error}")

    if should_log_overwrite:
        logger.add(f"[OVERWRITE] Copy overwrite: {source_file} -> {target_file}")
    shutil.copy2(source_file, target_file)


def copy_tree_contents(source_dir: Path, target_dir: Path, logger: Logger) -> None:
    for source_file in iter_files_recursive(source_dir):
        relative_path = source_file.relative_to(source_dir)
        target_file = target_dir / relative_path
        copy_file_with_log(source_file, target_file, logger)


def ensure_target_structure(target_root: Path, logger: Logger) -> Tuple[Path, Path]:
    target_input_dir = target_root / TARGET_INPUT_FOLDER_NAME
    target_output_system_dir = target_root / TARGET_OUTPUT_FOLDER_NAME / TARGET_OUTPUT_SYSTEM_FOLDER_NAME

    if not target_root.exists():
        logger.add(f"[CREATE FOLDER] Target root does not exist. Create: {target_root}")

    target_input_dir.mkdir(parents=True, exist_ok=True)
    target_output_system_dir.mkdir(parents=True, exist_ok=True)

    return target_input_dir, target_output_system_dir


def validate_base_path(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")


def run(path1: Path, path2: Path) -> Path:
    path1 = path1.expanduser().resolve()
    path2 = path2.expanduser().resolve()

    validate_base_path(path1, "Path1")
    path2.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(__file__).resolve().parent / LOG_FOLDER_NAME / f"{LOG_FILE_PREFIX}_{timestamp}.txt"
    logger = Logger(log_path)

    logger.add(f"Started at: {datetime.now().isoformat(timespec='seconds')}")
    logger.add(f"Path1: {path1}")
    logger.add(f"Path2: {path2}")
    logger.add(f"Root folder prefix: {ROOT_FOLDER_PREFIX}")
    logger.add(f"Source input folder: {SOURCE_INPUT_FOLDER_NAME}")
    logger.add(f"Source output folder: {SOURCE_OUTPUT_FOLDER_NAME}")
    logger.add(f"Target input folder: {TARGET_INPUT_FOLDER_NAME}")
    logger.add(f"Target output folder: {TARGET_OUTPUT_FOLDER_NAME}/{TARGET_OUTPUT_SYSTEM_FOLDER_NAME}")

    root_folders = list(iter_root_folders(path1))
    if not root_folders:
        logger.add("")
        logger.add("[WARNING] No root folders found in Path1.")

    for source_root in root_folders:
        target_root = path2 / source_root.name
        logger.section(f"Mapping root folder: {source_root.name}")
        logger.add(f"Source root: {source_root}")
        logger.add(f"Target root: {target_root}")

        target_input_dir, target_output_system_dir = ensure_target_structure(target_root, logger)

        source_input_dir = find_child_dir(source_root, SOURCE_INPUT_FOLDER_NAME)
        source_output_dir = find_child_dir(source_root, SOURCE_OUTPUT_FOLDER_NAME)

        if source_input_dir is None:
            logger.add(f"[SKIP] Source input folder not found: {source_root / SOURCE_INPUT_FOLDER_NAME}")
        else:
            logger.add(f"[COPY INPUT] {source_input_dir} -> {target_input_dir}")
            copy_tree_contents(source_input_dir, target_input_dir, logger)

        if source_output_dir is None:
            logger.add(f"[SKIP] Source output folder not found: {source_root / SOURCE_OUTPUT_FOLDER_NAME}")
        else:
            logger.add(f"[COPY OUTPUT] {source_output_dir} -> {target_output_system_dir}")
            copy_tree_contents(source_output_dir, target_output_system_dir, logger)

    logger.add("")
    logger.add(f"Finished at: {datetime.now().isoformat(timespec='seconds')}")
    logger.write()
    return log_path


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"Copy files from Path1 UT*/{SOURCE_INPUT_FOLDER_NAME} "
            f"to Path2 UT*/{TARGET_INPUT_FOLDER_NAME} and "
            f"from Path1 UT*/{SOURCE_OUTPUT_FOLDER_NAME} "
            f"to Path2 UT*/{TARGET_OUTPUT_FOLDER_NAME}/{TARGET_OUTPUT_SYSTEM_FOLDER_NAME}."
        )
    )
    parser.add_argument("path1", nargs="?", help="Source base path containing UT folders.")
    parser.add_argument("path2", nargs="?", help="Target base path containing/mirroring UT folders.")
    return parser.parse_args(argv)


def prompt_for_path(label: str) -> Path:
    while True:
        value = input(f"Nhap {label}: ").strip().strip('"')
        if value:
            return Path(value)
        print(f"{label} khong duoc de trong.")


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    path1 = Path(args.path1) if args.path1 else prompt_for_path("Path1")
    path2 = Path(args.path2) if args.path2 else prompt_for_path("Path2")

    try:
        log_path = run(path1, path2)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Hoan thanh copy.")
    print(f"Log file: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
