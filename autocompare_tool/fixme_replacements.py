from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from openpyxl import load_workbook
from openpyxl.styles import Alignment

from .excel_writer import WorkbookFixmeEntry


@dataclass(frozen=True)
class FixmeReplacementResult:
    workbook_count: int
    cell_count: int
    selected_entry_count: int


def apply_fixme_replacements(
    entries: Sequence[WorkbookFixmeEntry],
    notes_by_entry_index: Mapping[int, str],
) -> FixmeReplacementResult:
    replacements: dict[tuple[Path, str, int, int], list[str]] = defaultdict(list)

    for entry_index, note in notes_by_entry_index.items():
        note = note.strip()
        if not note or entry_index < 0 or entry_index >= len(entries):
            continue
        entry = entries[entry_index]
        key = (entry.workbook_path, entry.sheet_name, entry.worksheet_row, entry.fixme_column)
        replacements[key].append(note)

    if not replacements:
        return FixmeReplacementResult(workbook_count=0, cell_count=0, selected_entry_count=0)

    by_workbook: dict[Path, list[tuple[str, int, int, list[str]]]] = defaultdict(list)
    for (workbook_path, sheet_name, row, column), notes in replacements.items():
        by_workbook[workbook_path].append((sheet_name, row, column, notes))

    for workbook_path, cell_updates in by_workbook.items():
        workbook = load_workbook(workbook_path)
        for sheet_name, row, column, notes in cell_updates:
            if sheet_name not in workbook.sheetnames:
                continue
            worksheet = workbook[sheet_name]
            unique_notes = _unique_in_order(notes)
            cell = worksheet.cell(row, column)
            cell.value = "\n".join(unique_notes)
            cell.alignment = Alignment(wrap_text=True)
        workbook.save(workbook_path)

    return FixmeReplacementResult(
        workbook_count=len(by_workbook),
        cell_count=len(replacements),
        selected_entry_count=sum(1 for note in notes_by_entry_index.values() if note.strip()),
    )


def _unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value not in seen:
            unique_values.append(value)
            seen.add(value)
    return unique_values
