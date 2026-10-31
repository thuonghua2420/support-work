from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                # Whitespace-only differences are quoted so they stay visible.
                self.assertIn('Old:"LF\nvalue"', line_break_difference)
                self.assertIn('New:"LF\n\nvalue"', line_break_difference)
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

    def test_hints_expose_type_and_whitespace_differences_that_look_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = Workbook()
            old.active.title = "S"
            old.active["A1"] = "5"
            old.active["A2"] = "trail "
            old.active["A3"] = "a  b"
            old.save(root / "old.xlsx")
            new = Workbook()
            new.active.title = "S"
            new.active["A1"] = 5
            new.active["A2"] = "trail"
            new.active["A3"] = "a b"
            new.save(root / "new.xlsx")

            result = compare_excel_workbooks(root / "old.xlsx", root / "new.xlsx", root / "out.xlsx")

            samples = {item["cell"]: (item["old"], item["new"]) for item in result.sheets[0].samples}
            self.assertEqual(("5 (văn bản)", "5 (số)"), samples["A1"])
            self.assertEqual(('"trail "', '"trail"'), samples["A2"])
            self.assertEqual(('"a  b"', '"a b"'), samples["A3"])

    def test_formula_cached_results_are_compared_when_both_files_store_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name, cached in (("old.xlsx", 20), ("new.xlsx", 30), ("none.xlsx", None)):
                workbook = Workbook()
                workbook.active.title = "S"
                workbook.active["A1"] = 10
                workbook.active["B1"] = "=A1*2"
                workbook.save(root / name)
                if cached is not None:
                    _store_cached_value(root / name, "B1", cached)

            same_formula = compare_excel_workbooks(root / "old.xlsx", root / "new.xlsx", root / "a.xlsx")
            self.assertEqual(1, same_formula.difference_count)
            self.assertEqual("=A1*2 → 20", same_formula.sheets[0].samples[0]["old"])
            self.assertEqual("=A1*2 → 30", same_formula.sheets[0].samples[0]["new"])

            no_cache = compare_excel_workbooks(root / "old.xlsx", root / "none.xlsx", root / "b.xlsx")
            self.assertEqual(0, no_cache.difference_count)
            self.assertTrue(no_cache.identical)

    def test_pairing_by_position_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old = Workbook()
            old.active.title = "Before"
            old.active["A1"] = "x"
            old.save(root / "old.xlsx")
            new = Workbook()
            new.active.title = "After"
            new.active["A1"] = "x"
            new.save(root / "new.xlsx")

            paired = compare_excel_workbooks(root / "old.xlsx", root / "new.xlsx", root / "a.xlsx")
            self.assertEqual(["position"], [item.pairing for item in paired.sheets])
            self.assertEqual(0, paired.difference_count)

            separate = compare_excel_workbooks(
                root / "old.xlsx", root / "new.xlsx", root / "b.xlsx", pair_by_position=False
            )
            self.assertEqual(["old_only", "new_only"], [item.pairing for item in separate.sheets])
            self.assertFalse(separate.identical)
            self.assertEqual(1, separate.missing_new_sheet_count)
            self.assertEqual(1, separate.missing_old_sheet_count)

    def test_locked_output_reports_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("old.xlsx", "new.xlsx"):
                Workbook().save(root / name)
            with patch.object(Workbook, "save", side_effect=PermissionError("locked")):
                with self.assertRaisesRegex(PermissionError, "đóng file"):
                    compare_excel_workbooks(root / "old.xlsx", root / "new.xlsx", root / "out.xlsx")


def _store_cached_value(path: Path, coordinate: str, value: object) -> None:
    """Emulate Excel saving a formula result, which openpyxl itself never writes."""
    import re
    import shutil
    import zipfile

    temporary = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                pattern = rf'(<c r="{coordinate}"[^>]*><f>[^<]*</f>)<v\s*/>|(<c r="{coordinate}"[^>]*><f>[^<]*</f>)'
                text = re.sub(pattern, lambda match: f"{match.group(1) or match.group(2)}<v>{value}</v>", text, count=1)
                data = text.encode("utf-8")
            target.writestr(item, data)
    shutil.move(str(temporary), path)


if __name__ == "__main__":
    unittest.main()
