from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CsvTable:
    headers: list[str]
    rows: list[dict[str, str]]


def read_csv_table(path: Path) -> CsvTable:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return _read_csv_table(path, encoding)
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    return CsvTable(headers=[], rows=[])


def _read_csv_table(path: Path, encoding: str) -> CsvTable:
    with path.open("r", encoding=encoding, newline="") as file:
        reader = csv.reader(file)
        try:
            headers = next(reader)
        except StopIteration:
            return CsvTable(headers=[], rows=[])

        headers = [str(header) for header in headers]
        rows: list[dict[str, str]] = []
        for raw_row in reader:
            row: dict[str, str] = {}
            for index, header in enumerate(headers):
                row[header] = raw_row[index] if index < len(raw_row) else ""
            rows.append(row)

        return CsvTable(headers=headers, rows=rows)
