from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dbeaver_csv import read_dbeaver_csv


@dataclass(frozen=True)
class CsvTable:
    headers: list[str]
    rows: list[dict[str, str | None]]


def read_csv_table(path: Path) -> CsvTable:
    # Reuse the DBeaver-compatible parser so compare can distinguish:
    # unquoted blank (NULL) from quoted empty string ("").
    table = read_dbeaver_csv(path)
    rows: list[dict[str, str | None]] = []
    for raw_row in table.rows:
        row: dict[str, str | None] = {}
        for index, header in enumerate(table.headers):
            row[header] = raw_row[index] if index < len(raw_row) else None
        rows.append(row)
    return CsvTable(headers=table.headers, rows=rows)
