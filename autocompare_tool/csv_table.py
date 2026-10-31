from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .dbeaver_csv import read_dbeaver_csv
from .compare_diagnostics import compare_context


@dataclass(frozen=True)
class CsvTable:
    headers: list[str]
    rows: list[dict[str, str | None]]
    line_ranges: list[tuple[int, int]] = field(default_factory=list, compare=False)


def read_csv_table(path: Path) -> CsvTable:
    # Reuse the DBeaver-compatible parser so compare can distinguish:
    # unquoted blank (NULL) from quoted empty string ("").
    with compare_context("Đọc và kiểm tra CSV", **{"File CSV": path}):
        table = read_dbeaver_csv(path, strict=True)
        rows: list[dict[str, str | None]] = []
        for raw_row in table.rows:
            row: dict[str, str | None] = {}
            for index, header in enumerate(table.headers):
                row[header] = raw_row[index] if index < len(raw_row) else None
            rows.append(row)
        return CsvTable(headers=table.headers, rows=rows, line_ranges=table.line_ranges)
