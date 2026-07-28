from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from openpyxl import Workbook, load_workbook

    from autocompare_tool.file_utilities import (
        delete_contains_text,
        delete_empty_folders,
        find_empty_folders,
        move_files_contains_text,
        rename_contains_text,
        rename_exact_name,
        rename_excel_sheets_contains,
    )
except ImportError:  # pragma: no cover
    Workbook = None
    load_workbook = None
    delete_contains_text = None
    delete_empty_folders = None
    find_empty_folders = None
    move_files_contains_text = None
    rename_contains_text = None
    rename_exact_name = None
    rename_excel_sheets_contains = None


@unittest.skipIf(rename_exact_name is None, "file utility dependencies are not installed")
class FileUtilityTests(unittest.TestCase):
    def test_rename_exact_and_contains_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "old.txt").write_text("file", encoding="utf-8")
            (root / "draft_folder").mkdir()
            (root / "draft_folder" / "draft_file.txt").write_text("file", encoding="utf-8")

            exact_summary = rename_exact_name(root, "old.txt", "new.txt", include_files=True, include_folders=False)
            contains_summary = rename_contains_text(root, "draft", "final")

            self.assertEqual(exact_summary.changed_count, 1)
            self.assertEqual(contains_summary.changed_count, 2)
            self.assertTrue((root / "new.txt").exists())
            self.assertTrue((root / "final_folder" / "final_file.txt").exists())

    def test_delete_contains_and_empty_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "remove_file.txt").write_text("file", encoding="utf-8")
            (root / "remove_folder").mkdir()
            (root / "parent" / "child").mkdir(parents=True)

            delete_summary = delete_contains_text(root, "remove")
            empty_summary = find_empty_folders(root)
            delete_empty_summary = delete_empty_folders(root)

            self.assertEqual(delete_summary.changed_count, 2)
            self.assertGreaterEqual(empty_summary.found_count, 1)
            self.assertGreaterEqual(delete_empty_summary.changed_count, 2)
            self.assertFalse((root / "remove_file.txt").exists())
            self.assertFalse((root / "remove_folder").exists())
            self.assertFalse((root / "parent").exists())

    def test_move_files_contains_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            (nested / "invoice.csv").write_text("file", encoding="utf-8")

            summary = move_files_contains_text(root, "invoice", "Matched")

            self.assertEqual(summary.changed_count, 1)
            self.assertTrue((nested / "Matched" / "invoice.csv").exists())

    @unittest.skipIf(Workbook is None or load_workbook is None, "openpyxl is not installed")
    def test_rename_excel_sheets_contains_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "book.xlsx"
            workbook = Workbook()
            workbook.active.title = "before_sheet"
            workbook.create_sheet("keep")
            workbook.save(path)

            summary = rename_excel_sheets_contains(path, "before", "after")

            self.assertEqual(summary.changed_count, 1)
            workbook = load_workbook(path)
            self.assertIn("after_sheet", workbook.sheetnames)
            self.assertIn("keep", workbook.sheetnames)


if __name__ == "__main__":
    unittest.main()
