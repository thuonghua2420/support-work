from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from openpyxl import load_workbook
    from autocompare_tool.processor import process_root
except ImportError:  # pragma: no cover
    load_workbook = None
    process_root = None

from autocompare_tool.constants import (
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


@unittest.skipIf(load_workbook is None, "openpyxl is not installed")
class ProcessorAndExcelTests(unittest.TestCase):
    def test_process_root_copies_and_creates_workbooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case = root / "UT01-001"
            input_dir = case / INPUT_DIR
            output_dir = case / OUTPUT_DIR
            before_new = output_dir / BEFORE_NEW_DIR
            before_current = output_dir / BEFORE_CURRENT_DIR
            after_new = output_dir / AFTER_NEW_DIR
            after_current = output_dir / AFTER_CURRENT_DIR

            for folder in (input_dir, before_new, before_current, after_new, after_current):
                folder.mkdir(parents=True)

            _write_text(input_dir / "table.csv", "id,name\n5,before\n")
            _write_text(input_dir / "before_only.csv", "id,name\n999,extra\n")
            _write_text(before_new / "stale.csv", "id,name\n999,stale\n")
            _write_text(after_new / "table.csv", "id,name\n2,insert\n5,after\n")
            _write_text(after_current / "table.csv", "id,name\n5,before\n")

            self.assertIsNotNone(process_root)
            summary = process_root(root)

            self.assertFalse(summary.errors)
            self.assertFalse((before_new / "stale.csv").exists())
            self.assertTrue((before_new / "table.csv").exists())
            self.assertTrue((before_current / "table.csv").exists())
            self.assertFalse((before_new / "before_only.csv").exists())
            self.assertFalse((before_current / "before_only.csv").exists())

            compare_new = output_dir / COMPARE_DIR / COMPARE_NEW_FILE
            compare_current = output_dir / COMPARE_DIR / COMPARE_CURRENT_FILE
            self.assertTrue(compare_new.exists())
            self.assertTrue(compare_current.exists())

            workbook = load_workbook(compare_new)
            self.assertIn("table", workbook.sheetnames)
            worksheet = workbook["table"]
            self.assertEqual(worksheet["A1"].value, "差分行数")
            self.assertEqual(worksheet["A2"].value, "前列名")
            self.assertEqual(worksheet["B2"].value, "後列名")
            self.assertEqual(worksheet["C2"].value, "前:1行目")
            self.assertEqual(worksheet["D2"].value, "後:1行目")
            self.assertEqual(worksheet["B1"].value, 2)
            self.assertEqual(worksheet["F4"].value, "after")
            self.assertEqual(worksheet["H4"].value, "FIXME")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="")


if __name__ == "__main__":
    unittest.main()
