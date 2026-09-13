from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

try:
    from openpyxl import Workbook, load_workbook
    from autocompare_tool.app_config import ExcelCompareStyleConfig, load_app_config
    from autocompare_tool.excel_writer import WorkbookFixmeEntry, write_compare_workbook_with_fixmes
    from autocompare_tool.fixme_replacements import apply_fixme_replacements
    from autocompare_tool.folder_compare import compare_csv_folder_pairs, compare_csv_folders, preview_folder_compare_pairs
    from autocompare_tool.processor import process_root
except ImportError:  # pragma: no cover
    apply_fixme_replacements = None
    compare_csv_folders = None
    compare_csv_folder_pairs = None
    preview_folder_compare_pairs = None
    ExcelCompareStyleConfig = None
    Workbook = None
    WorkbookFixmeEntry = None
    load_workbook = None
    process_root = None
    write_compare_workbook_with_fixmes = None

from autocompare_tool.constants import (
    AFTER_CURRENT_DIR,
    AFTER_NEW_DIR,
    BEFORE_CURRENT_DIR,
    BEFORE_NEW_DIR,
    COMPARE_AFTER_AFTER_FILE,
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

            _write_text(input_dir / "table.csv", "id,name\n5,before\n2,before-2\n9,outside\n")
            _write_text(input_dir / "before_only.csv", "id,name\n999,extra\n")
            _write_text(before_new / "stale.csv", "id,name\n999,stale\n")
            _write_text(after_new / "table.csv", "id,name\n2,insert\n5,after\n")
            _write_text(after_current / "table.csv", "id,name\n5,before\n")

            self.assertIsNotNone(process_root)
            config = replace(load_app_config(), update_compare_keys={"table": ("id",)})
            summary = process_root(root, config=config, copy_input=True)

            self.assertFalse(summary.errors)
            self.assertTrue((before_new / "stale.csv").exists())
            self.assertTrue((before_new / "table.csv").exists())
            self.assertTrue(before_current.exists())
            self.assertTrue((before_new / "before_only.csv").exists())

            compare_new = output_dir / COMPARE_DIR / COMPARE_NEW_FILE
            compare_current = output_dir / COMPARE_DIR / COMPARE_CURRENT_FILE
            compare_after_after = output_dir / COMPARE_DIR / COMPARE_AFTER_AFTER_FILE
            self.assertTrue(compare_new.exists())
            self.assertTrue(compare_current.exists())
            self.assertTrue(compare_after_after.exists())
            self.assertGreater(len(summary.fixme_entries), 0)

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
            self.assertEqual(worksheet["J4"].value, "FIXME")

    def test_process_root_respects_selected_compare_workflows_and_applies_notes(self) -> None:
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

            _write_text(input_dir / "table.csv", "id,name\n1,before\n")
            _write_text(after_new / "table.csv", "id,name\n1,after\n")
            _write_text(after_current / "table.csv", "id,name\n1,before\n")
            stale_compare_dir = output_dir / COMPARE_DIR
            stale_compare_dir.mkdir()
            _write_text(stale_compare_dir / COMPARE_CURRENT_FILE, "stale")
            _write_text(stale_compare_dir / COMPARE_AFTER_AFTER_FILE, "stale")

            config = replace(load_app_config(), update_compare_keys={"table": ("id",)})
            summary = process_root(root, selected_workflow_keys={"htm_before_after"}, config=config, copy_input=True)

            compare_new = output_dir / COMPARE_DIR / COMPARE_NEW_FILE
            compare_current = output_dir / COMPARE_DIR / COMPARE_CURRENT_FILE
            compare_after_after = output_dir / COMPARE_DIR / COMPARE_AFTER_AFTER_FILE
            self.assertTrue(compare_new.exists())
            self.assertEqual(compare_current.read_text(), "stale")
            self.assertEqual(compare_after_after.read_text(), "stale")
            self.assertEqual(len(summary.fixme_entries), 1)

            result = apply_fixme_replacements(summary.fixme_entries, {0: "KNOWN_DIFF"})
            self.assertEqual(result.cell_count, 1)

            workbook = load_workbook(compare_new)
            self.assertEqual(workbook["table"]["F4"].value, "KNOWN_DIFF")
            self.assertFalse(workbook["table"]["F4"].alignment.wrap_text)

    def test_apply_fixme_replacements_updates_multiple_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook_path = Path(temp_dir) / "compare.xlsx"
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = "table"
            workbook.save(workbook_path)
            entries = [
                WorkbookFixmeEntry("UT01", workbook_path, "compare.xlsx", "table.csv", "table", "name", "old", "new", 1, 3, 8),
                WorkbookFixmeEntry("UT01", workbook_path, "compare.xlsx", "table.csv", "table", "price", "10", "20", 1, 4, 8),
            ]

            result = apply_fixme_replacements(entries, {0: "KNOWN_DIFF", 1: "SPEC_CHANGE"})

            self.assertEqual(result.cell_count, 2)
            self.assertEqual(result.selected_entry_count, 2)
            workbook = load_workbook(workbook_path)
            self.assertEqual(workbook["table"]["H3"].value, "KNOWN_DIFF")
            self.assertEqual(workbook["table"]["H4"].value, "SPEC_CHANGE")

    def test_apply_fixme_replacements_updates_all_selected_workbooks_and_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "first.xlsx"
            second_path = root / "second.xlsx"
            first = Workbook()
            first.active.title = "customers"
            first.create_sheet("orders")
            first.save(first_path)
            second = Workbook()
            second.active.title = "details"
            second.save(second_path)
            entries = [
                WorkbookFixmeEntry("UT01", first_path, first_path.name, "customers.csv", "customers", "name", "a", "b", 1, 3, 8),
                WorkbookFixmeEntry("UT01", first_path, first_path.name, "orders.csv", "orders", "amount", "1", "2", 1, 4, 10),
                WorkbookFixmeEntry("UT02", second_path, second_path.name, "details.csv", "details", "status", "0", "1", 1, 5, 6),
            ]

            result = apply_fixme_replacements(entries, {0: "NOTE_A", 1: "NOTE_B", 2: "NOTE_C"})

            self.assertEqual((result.workbook_count, result.sheet_count, result.cell_count, result.selected_entry_count), (2, 3, 3, 3))
            first = load_workbook(first_path)
            second = load_workbook(second_path)
            try:
                self.assertEqual(first["customers"]["H3"].value, "NOTE_A")
                self.assertEqual(first["orders"]["J4"].value, "NOTE_B")
                self.assertEqual(second["details"]["F5"].value, "NOTE_C")
            finally:
                first.close()
                second.close()

    def test_compare_csv_folders_uses_all_csv_files_from_both_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()

            _write_text(left / "shared.csv", "id,name\n1,left\n")
            _write_text(right / "shared.csv", "id,name\n1,right\n")
            _write_text(left / "left_only.csv", "id,name\n2,left-only\n")
            _write_text(right / "right_only.csv", "id,name\n3,right-only\n")
            (left / "nested").mkdir()
            (right / "nested").mkdir()
            _write_text(left / "nested" / "child.csv", "id,name\n4,left-child\n")
            _write_text(right / "nested" / "child.csv", "id,name\n4,right-child\n")

            self.assertIsNotNone(compare_csv_folders)
            output = root / "folder_compare.xlsx"
            summary = compare_csv_folders(left, right, output)

            self.assertTrue(output.exists())
            self.assertEqual(summary.sheet_count, 4)
            self.assertGreaterEqual(len(summary.fixme_entries), 1)

            workbook = load_workbook(output)
            self.assertEqual(set(workbook.sheetnames), {"left_only", "nested_child", "right_only", "shared"})

    def test_compare_csv_folder_pairs_exports_one_workbook_per_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "left"
            right = root / "right"
            output = root / "out"
            left.mkdir()
            right.mkdir()

            _write_text(left / "customer_20260905_120000.csv", "id,name\n1,A\n")
            _write_text(left / "order_20260905_120000.csv", "id,total\n1,10\n")
            _write_text(right / "customer_20260905_120500.csv", "id,name\n1,B\n")
            _write_text(right / "order_20260905_120500.csv", "id,total\n1,10\n")

            self.assertIsNotNone(compare_csv_folder_pairs)
            pairs = [
                {
                    "left_name": "customer_20260905_120000.csv",
                    "right_name": "customer_20260905_120500.csv",
                    "output_name": "customer_compare.xlsx",
                },
                {
                    "left_name": "order_20260905_120000.csv",
                    "right_name": "order_20260905_120500.csv",
                    "output_name": "order_compare.xlsx",
                },
            ]
            summary = compare_csv_folder_pairs(left, right, output, pairs)

            self.assertEqual(summary.workbook_count, 2)
            self.assertEqual(summary.sheet_count, 2)
            self.assertTrue((output / "customer_compare.xlsx").exists())
            self.assertTrue((output / "order_compare.xlsx").exists())
            self.assertEqual(len(preview_folder_compare_pairs(left, right)), 2)

    def test_compare_workbook_uses_configurable_style_colors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            _write_text(before / "table.csv", "id,name\n1,before\n")
            _write_text(after / "table.csv", "id,name\n1,after\n")
            output = root / "compare.xlsx"
            style = ExcelCompareStyleConfig(
                base_font_color="111111",
                header_font_color="222222",
                diff_font_color="333333",
                a1_font_color="999999",
                fixme_font_color="444444",
                a1_fill_color="ABCDEF",
                header_fill_color="123456",
                name_fill_color="654321",
                diff_fill_color="FEDCBA",
            )

            write_compare_workbook_with_fixmes(before, after, output, excel_style=style)

            workbook = load_workbook(output)
            worksheet = workbook["table"]
            self.assertTrue(worksheet["A1"].fill.fgColor.rgb.endswith("ABCDEF"))
            self.assertTrue(worksheet["A1"].font.color.rgb.endswith("999999"))
            self.assertFalse(worksheet["A1"].font.bold)
            self.assertTrue(worksheet["A2"].fill.fgColor.rgb.endswith("123456"))
            self.assertTrue(worksheet["A3"].fill.fgColor.rgb.endswith("654321"))
            self.assertTrue(worksheet["C4"].fill.fgColor.rgb.endswith("FEDCBA"))
            self.assertTrue(worksheet["C4"].font.color.rgb.endswith("333333"))
            self.assertTrue(worksheet["C4"].font.bold)
            self.assertTrue(worksheet["F4"].font.color.rgb.endswith("444444"))
            self.assertFalse(worksheet["F4"].font.bold)
            self.assertFalse(worksheet["F4"].alignment.wrap_text)

    def test_compare_workbook_displays_null_but_leaves_empty_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            _write_text(before / "table.csv", 'id,empty_value,null_value\n"1","",\n')
            _write_text(after / "table.csv", 'id,empty_value,null_value\n"1",,""\n')
            output = root / "compare.xlsx"

            write_compare_workbook_with_fixmes(before, after, output)

            workbook = load_workbook(output)
            worksheet = workbook["table"]
            self.assertIsNone(worksheet["C4"].value)
            self.assertEqual("NULL", worksheet["D4"].value)
            self.assertEqual("NULL", worksheet["C5"].value)
            self.assertIsNone(worksheet["D5"].value)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="")


if __name__ == "__main__":
    unittest.main()
