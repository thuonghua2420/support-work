from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.styles import Font

    from autocompare_tool.excel_compare import compare_excel_workbooks
except ImportError:  # pragma: no cover - dependency guard for broken local environments
    Workbook = None
    load_workbook = None
    CellRichText = None
    TextBlock = None
    compare_excel_workbooks = None


@unittest.skipIf(Workbook is None, "openpyxl is not installed")
class ExcelCompareTests(unittest.TestCase):
    def test_writes_source_and_compare_sheet_triplets_with_rich_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / "old.xlsx"
            new_path = root / "new.xlsx"
            output_path = root / "result.xlsx"

            old = Workbook()
            old_sheet = old.active
            old_sheet.title = "Users"
            old_sheet["A1"] = "same"
            old_sheet["B1"] = 2
            old_sheet["B1"].font = Font(name="Arial", color="FF0000")
            old_sheet["C2"] = "LF\nvalue"
            old_sheet.column_dimensions["B"].width = 22
            old.save(old_path)

            new = Workbook()
            new_sheet = new.active
            new_sheet.title = "Users"
            new_sheet["A1"] = "same"
            new_sheet["B1"] = 3
            new_sheet["C2"] = "LF\r\nvalue"
            new.save(new_path)

            result = compare_excel_workbooks(old_path, new_path, output_path)

            self.assertEqual(1, result.sheet_pair_count)
            self.assertEqual(2, result.difference_count)
            workbook = load_workbook(output_path, rich_text=True, data_only=False)
            try:
                self.assertEqual(["Users_Old", "Users_New", "Users_compare"], workbook.sheetnames)
                self.assertEqual(2, workbook["Users_Old"]["B1"].value)
                self.assertEqual(3, workbook["Users_New"]["B1"].value)
                self.assertEqual(22, workbook["Users_Old"].column_dimensions["B"].width)
                self.assertIsNone(workbook["Users_compare"]["A1"].value)

                rich_value = workbook["Users_compare"]["B1"].value
                self.assertIsInstance(rich_value, CellRichText)
                self.assertEqual("Old:2 # New:3", str(rich_value))
                bold_parts = [part.text for part in rich_value if isinstance(part, TextBlock) and part.font.b]
                self.assertEqual(["Old:", "New:"], bold_parts)
                line_break_difference = str(workbook["Users_compare"]["C2"].value)
                self.assertIn("Old:LF\nvalue", line_break_difference)
                self.assertIn("New:LF\n\nvalue", line_break_difference)
            finally:
                workbook.close()

    def test_pairs_equal_names_first_then_remaining_sheets_by_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / "old.xlsx"
            new_path = root / "new.xlsx"

            old = Workbook()
            old.active.title = "Shared"
            old["Shared"]["A1"] = "same"
            old_only = old.create_sheet("Only Old")
            old_only["A1"] = "removed"
            old.save(old_path)

            new = Workbook()
            new.active.title = "Shared"
            new["Shared"]["A1"] = "same"
            new_only = new.create_sheet("Only New")
            new_only["A1"] = "added"
            new_tail = new.create_sheet("New Tail")
            new_tail["A1"] = "tail"
            new.save(new_path)

            result = compare_excel_workbooks(old_path, new_path, root / "result")

            self.assertEqual(3, result.sheet_pair_count)
            self.assertEqual(2, result.difference_count)
            self.assertEqual(1, result.missing_old_sheet_count)
            self.assertEqual(0, result.missing_new_sheet_count)
            self.assertEqual(".xlsx", result.output_path.suffix)
            workbook = load_workbook(result.output_path, rich_text=True)
            try:
                self.assertEqual(
                    [
                        "Shared_Old", "Shared_New", "Shared_compare",
                        "Only Old_Old", "Only New_New", "Only New_compare",
                        "New Tail_Old", "New Tail_New", "New Tail_compare",
                    ],
                    workbook.sheetnames,
                )
                self.assertEqual("Old:removed # New:added", str(workbook["Only New_compare"]["A1"].value))
                self.assertEqual("Old: # New:tail", str(workbook["New Tail_compare"]["A1"].value))
            finally:
                workbook.close()

    def test_long_sheet_names_keep_the_required_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            name = "A" * 31
            for file_name in ("old.xlsx", "new.xlsx"):
                workbook = Workbook()
                workbook.active.title = name
                workbook.save(root / file_name)

            compare_excel_workbooks(root / "old.xlsx", root / "new.xlsx", root / "result.xlsx")

            workbook = load_workbook(root / "result.xlsx")
            try:
                self.assertTrue(workbook.sheetnames[0].endswith("_Old"))
                self.assertTrue(workbook.sheetnames[1].endswith("_New"))
                self.assertTrue(workbook.sheetnames[2].endswith("_compare"))
                self.assertTrue(all(len(name) <= 31 for name in workbook.sheetnames))
            finally:
                workbook.close()


if __name__ == "__main__":
    unittest.main()
