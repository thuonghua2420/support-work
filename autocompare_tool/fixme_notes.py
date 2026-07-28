from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

NOTE_FILE_NAME = "fixme_notes.json"


@dataclass(frozen=True)
class FixmeNote:
    value: str
    meaning: str


class FixmeNoteStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_note_path()

    def load(self) -> list[FixmeNote]:
        if not self.path.exists():
            return []

        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError:
            return []

        raw_notes = data.get("notes", []) if isinstance(data, dict) else []
        notes: list[FixmeNote] = []
        for item in raw_notes:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value", "")).strip()
            meaning = str(item.get("meaning", "")).strip()
            if value:
                notes.append(FixmeNote(value=value, meaning=meaning))
        return _deduplicate_notes(notes)

    def save(self, notes: list[FixmeNote]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"notes": [{"value": note.value, "meaning": note.meaning} for note in _deduplicate_notes(notes)]}
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def upsert(self, value: str, meaning: str) -> list[FixmeNote]:
        value = value.strip()
        meaning = meaning.strip()
        if not value:
            raise ValueError("Vui lòng nhập giá trị ghi chú.")

        notes = [note for note in self.load() if note.value != value]
        notes.append(FixmeNote(value=value, meaning=meaning))
        notes.sort(key=lambda note: note.value.lower())
        self.save(notes)
        return notes

    def replace(self, old_value: str, value: str, meaning: str) -> list[FixmeNote]:
        old_value = old_value.strip()
        value = value.strip()
        meaning = meaning.strip()
        if not value:
            raise ValueError("Vui lòng nhập giá trị ghi chú.")

        notes = [note for note in self.load() if note.value not in {old_value, value}]
        notes.append(FixmeNote(value=value, meaning=meaning))
        notes.sort(key=lambda note: note.value.lower())
        self.save(notes)
        return notes

    def delete(self, value: str) -> list[FixmeNote]:
        value = value.strip()
        if not value:
            raise ValueError("Vui lòng chọn giá trị ghi chú cần xóa.")
        notes = [note for note in self.load() if note.value != value]
        self.save(notes)
        return notes


def default_note_path() -> Path:
    return Path(__file__).resolve().parent.parent / NOTE_FILE_NAME


def _deduplicate_notes(notes: list[FixmeNote]) -> list[FixmeNote]:
    by_value: dict[str, FixmeNote] = {}
    for note in notes:
        by_value[note.value] = note
    return sorted(by_value.values(), key=lambda note: note.value.lower())
