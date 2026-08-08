from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PRESET_FILE_NAME = "excel_format_presets.json"
CELL_ADDRESS_PATTERN = re.compile(r"^\$?[A-Za-z]{1,3}\$?[1-9][0-9]*$")
PAIR_PATTERN = re.compile(
    r"^\(\s*(?P<text>.+?)\s*,\s*(?P<cell>\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)\s*\)$"
)


@dataclass(frozen=True)
class FontSizeExclusionRule:
    text: str
    cell_address: str | None = None

    @property
    def display_value(self) -> str:
        if self.cell_address:
            return f"({self.text}, {self.cell_address})"
        return self.text


@dataclass(frozen=True)
class ExcelFormatPreset:
    name: str
    font_name: str
    font_size: float
    exclusions: tuple[str, ...]


class ExcelFormatPresetStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_preset_path()

    def load(self) -> list[ExcelFormatPreset]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return []

        raw_presets = data.get("presets", []) if isinstance(data, dict) else []
        presets: list[ExcelFormatPreset] = []
        for item in raw_presets:
            if not isinstance(item, dict):
                continue
            try:
                preset = build_preset(
                    name=str(item.get("name", "")),
                    font_name=str(item.get("font_name", "")),
                    font_size=item.get("font_size", 11),
                    exclusions=item.get("exclusions", []),
                )
            except (TypeError, ValueError):
                continue
            presets.append(preset)
        return _deduplicate_presets(presets)

    def save(self, presets: list[ExcelFormatPreset]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalized = _deduplicate_presets(presets)
        payload = {
            "presets": [
                {
                    "name": preset.name,
                    "font_name": preset.font_name,
                    "font_size": preset.font_size,
                    "exclusions": list(preset.exclusions),
                }
                for preset in normalized
            ]
        }
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")

    def upsert(
        self,
        name: str,
        font_name: str,
        font_size: object,
        exclusions: str | Iterable[object],
    ) -> list[ExcelFormatPreset]:
        preset = build_preset(name, font_name, font_size, exclusions)
        presets = [item for item in self.load() if item.name.casefold() != preset.name.casefold()]
        presets.append(preset)
        self.save(presets)
        return self.load()

    def delete(self, name: str) -> list[ExcelFormatPreset]:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Vui lòng chọn preset cần xóa.")
        presets = [item for item in self.load() if item.name.casefold() != normalized_name.casefold()]
        self.save(presets)
        return self.load()


def build_preset(
    name: str,
    font_name: str,
    font_size: object,
    exclusions: str | Iterable[object],
) -> ExcelFormatPreset:
    normalized_name = str(name).strip()
    if not normalized_name:
        raise ValueError("Vui lòng nhập tên preset.")
    normalized_font = str(font_name).strip()
    if not normalized_font:
        raise ValueError("Vui lòng nhập tên font chữ.")
    normalized_size = normalize_font_size(font_size)
    rules = parse_exclusion_rules(exclusions)
    return ExcelFormatPreset(
        name=normalized_name,
        font_name=normalized_font,
        font_size=normalized_size,
        exclusions=tuple(rule.display_value for rule in rules),
    )


def parse_exclusion_rules(raw_value: str | Iterable[object] | None) -> list[FontSizeExclusionRule]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        values = raw_value.splitlines()
    else:
        values = [str(item) for item in raw_value]

    rules: list[FontSizeExclusionRule] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in values:
        item = str(raw_item).strip()
        if not item:
            continue
        match = PAIR_PATTERN.fullmatch(item)
        if match:
            text = match.group("text").strip()
            address = match.group("cell").upper()
        else:
            if item.startswith("(") or item.endswith(")"):
                raise ValueError(
                    f"Quy tắc không hợp lệ: {item}. Dùng Text hoặc (Text, A1), mỗi quy tắc một dòng."
                )
            text = item
            address = ""
        if not text:
            raise ValueError("Text loại trừ không được để trống.")
        if address and not CELL_ADDRESS_PATTERN.fullmatch(address):
            raise ValueError(f"Địa chỉ cell không hợp lệ: {address}.")
        key = (text.casefold(), address.replace("$", ""))
        if key in seen:
            continue
        seen.add(key)
        rules.append(FontSizeExclusionRule(text=text, cell_address=address or None))
    return rules


def normalize_font_size(raw_value: object) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cỡ chữ phải là một số.") from exc
    if not 1 <= value <= 409:
        raise ValueError("Cỡ chữ phải nằm trong khoảng 1 đến 409.")
    return value


def default_preset_path() -> Path:
    return Path(__file__).resolve().parent.parent / PRESET_FILE_NAME


def _deduplicate_presets(presets: list[ExcelFormatPreset]) -> list[ExcelFormatPreset]:
    by_name: dict[str, ExcelFormatPreset] = {}
    for preset in presets:
        by_name[preset.name.casefold()] = preset
    return sorted(by_name.values(), key=lambda item: item.name.casefold())
