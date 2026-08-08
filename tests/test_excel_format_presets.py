from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocompare_tool.excel_format_presets import (
    ExcelFormatPresetStore,
    normalize_font_size,
    parse_exclusion_rules,
)


class ExcelFormatPresetTests(unittest.TestCase):
    def test_parses_plain_and_address_specific_rules(self) -> None:
        rules = parse_exclusion_rules("Header\n(Title, a1)\nTotal\nheader")

        self.assertEqual(
            [("Header", None), ("Title", "A1"), ("Total", None)],
            [(rule.text, rule.cell_address) for rule in rules],
        )
        self.assertEqual(["Header", "(Title, A1)", "Total"], [rule.display_value for rule in rules])

    def test_rejects_invalid_pair_rule(self) -> None:
        with self.assertRaisesRegex(ValueError, "Dùng Text hoặc"):
            parse_exclusion_rules("(Header, first-cell)")

    def test_validates_excel_font_size_range(self) -> None:
        self.assertEqual(10.5, normalize_font_size("10.5"))
        with self.assertRaisesRegex(ValueError, "1 đến 409"):
            normalize_font_size(0)

    def test_preset_store_saves_updates_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "presets.json"
            store = ExcelFormatPresetStore(path)

            presets = store.upsert("UT chuẩn", "Meiryo UI", "11", "Header\n(Title, A1)")
            self.assertEqual(["UT chuẩn"], [item.name for item in presets])
            self.assertEqual(("Header", "(Title, A1)"), presets[0].exclusions)

            presets = store.upsert("ut CHUẨN", "Calibri", 12, ["Total"])
            self.assertEqual(1, len(presets))
            self.assertEqual("Calibri", presets[0].font_name)
            self.assertEqual(("Total",), presets[0].exclusions)

            presets = store.delete("UT chuẩn")
            self.assertEqual([], presets)
            self.assertEqual([], store.load())

    def test_store_ignores_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "presets.json"
            path.write_text("{not-json", encoding="utf-8")

            self.assertEqual([], ExcelFormatPresetStore(path).load())


if __name__ == "__main__":
    unittest.main()
