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
    from autocompare_tool.folder_compare import (
        compare_csv_folder_pairs,
        compare_csv_folder_pairs_to_workbook,
        compare_csv_folders,
        preview_folder_compare_pairs,
    )
    from autocompare_tool.processor import process_root
except ImportError:  # pragma: no cover
    apply_fixme_replacements = None
    compare_csv_folders = None
    compare_csv_folder_pairs = None
    compare_csv_folder_pairs_to_workbook = None
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
            self.assertFalse((before_new / "before_only.csv").exists())
            self.assertFalse((before_current / "before_only.csv").exists())

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

    def test_key_regression_keeps_layout_fixmes_source_counts_and_loader(self):
        from autocompare_tool.compare_record_counts import read_record_counts
        from autocompare_tool.compare_workbook_loader import _read_compare_entries
        from autocompare_tool.compare_workbook_view import CompareWorkbookReference, read_compare_sheet
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before, after = root / "before", root / "after"
            before.mkdir()
            after.mkdir()
            _write_text(before / "ORDERS.csv", "id,value\n234,same\n387,deleted\n634,old\n")
            _write_text(after / "ORDERS.csv", "id,value\n135,first\n234,same\n375,insert\n634,new\n")
            output = root / "compare.xlsx"
            result = write_compare_workbook_with_fixmes(before, after, output, key_columns_by_table={"Orders": ("ID",)})
            self.assertEqual(result.warnings, [])
            workbook = load_workbook(output)
            try:
                sheet = workbook["ORDERS"]
                self.assertEqual((sheet.max_row, sheet.max_column), (4, 14))
                for number, col in enumerate(range(3, 13, 2), 1):
                    self.assertEqual(sheet.cell(2, col).value, f"前:{number}行目")
                    self.assertEqual(sheet.cell(2, col + 1).value, f"後:{number}行目")
                self.assertEqual([sheet.cell(3, col).value for col in range(3, 13)],
                                 [None, "135", "234", "234", None, "375", "387", None, "634", "634"])
                self.assertEqual(sheet["N3"].value, "FIXME")
                self.assertEqual(sheet["N4"].value, "FIXME")
                self.assertEqual(sheet["B1"].value, 2)
                self.assertEqual(workbook.sheetnames, ["ORDERS"])
                self.assertNotIn("status", workbook.properties.description.lower())
            finally:
                workbook.close()
            self.assertEqual({(entry.record_number, entry.column_name) for entry in result.fixme_entries},
                             {(1, "id"), (1, "value"), (3, "id"), (3, "value"), (4, "id"), (4, "value"), (5, "value")})
            self.assertEqual((read_record_counts(output)[0]["left_count"], read_record_counts(output)[0]["right_count"]), (3, 4))
            reference = CompareWorkbookReference("UT01", output, output.name)
            loaded = _read_compare_entries(reference, load_app_config())
            self.assertEqual([(e.record_number, e.column_name, e.left_value, e.right_value) for e in loaded],
                             [(e.record_number, e.column_name, e.left_value, e.right_value) for e in result.fixme_entries])
            view = read_compare_sheet(reference, "ORDERS", [])
            self.assertEqual([item["status"] for item in view["record_statuses"]], ["INSERT", "UNCHANGED", "INSERT", "DELETE", "UPDATE"])
            self.assertEqual(view["status_counts"], {"INSERT": 2, "DELETE": 1, "UPDATE": 1, "UNCHANGED": 1})
            self.assertEqual(view["record_count_mismatch_pair_starts"], [3, 7, 9])

    def test_excel_limit_uses_union_pair_count_before_writing_sheet(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before, after = root / "before", root / "after"
            before.mkdir()
            after.mkdir()
            _write_text(before / "table.csv", "id\n1\n3\n")
            _write_text(after / "table.csv", "id\n2\n4\n")
            output = root / "compare.xlsx"
            output.write_bytes(b"keep existing output")
            with patch("autocompare_tool.excel_writer.MAX_COLUMN", 10), patch("autocompare_tool.excel_writer._write_sheet") as writer:
                with self.assertRaisesRegex(ValueError, "Số cặp record: 4"):
                    write_compare_workbook_with_fixmes(before, after, output, key_columns_by_table={"table": ("id",)})
            writer.assert_not_called()
            self.assertEqual(output.read_bytes(), b"keep existing output")

    def test_key_fallback_warning_has_table_paths_reason_and_positional_labels(self):
        cases = [(None, "id,value\n2,old\n1,old\n", "[update_compare_keys]"),
                 (("missing",), "id,value\n2,old\n1,old\n", "missing"),
                 (("id",), "id,value\n,old\n1,old\n", "NULL/blank"),
                 (("id",), 'id,value\n"",old\n1,old\n', "NULL/blank"),
                 (("id",), "id,value\n2,old\n2,old\n", "Duplicate")]
        for keys, text, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                before, after = root / "before", root / "after"
                before.mkdir()
                after.mkdir()
                _write_text(before / "table.csv", text)
                _write_text(after / "table.csv", "id,value\n1,new\n2,new\n")
                output = root / "compare.xlsx"
                result = write_compare_workbook_with_fixmes(before, after, output, key_columns_by_table={"table": keys} if keys else {})
                self.assertEqual(len(result.warnings), 1)
                for detail in (reason, "Sheet: table", "Table CSV: table", str(before / "table.csv"), str(after / "table.csv"),
                               str(output), "Key cấu hình", "Đã ghép theo vị trí dòng"):
                    self.assertIn(detail, result.warnings[0])
                workbook = load_workbook(output)
                try:
                    self.assertEqual((workbook.active["C2"].value, workbook.active["D2"].value), ("前:1行目", "後:1行目"))
                    self.assertEqual(workbook.active["D3"].value, "1")
                    self.assertEqual(workbook.active["F3"].value, "2")
                finally:
                    workbook.close()

    def test_reordered_key_diagnostic_points_to_original_csv_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before, after = root / "before", root / "after"
            before.mkdir()
            after.mkdir()
            for side in (before, after):
                for path in (before / "table.csv", after / "table.csv"):
                    _write_text(path, "id,value\n2,ok\n1,short\n")
                _write_text(side / "table.csv", 'id,value\n2,ok\n1,"' + "x" * 32768 + '"\n')
                with self.assertRaises(ValueError) as raised:
                    write_compare_workbook_with_fixmes(before, after, root / "compare.xlsx", key_columns_by_table={"table": ("id",)})
                message = str(raised.exception)
                for expected in ("Record CSV: 2", "Dòng vật lý CSV: 3", str(side / "table.csv"),
                                 "Ô Excel: C4" if side == before else "Ô Excel: D4"):
                    self.assertIn(expected, message)

    def test_all_folder_compare_modes_use_csv_stem_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            left, right = root / "left", root / "right"
            left.mkdir()
            right.mkdir()
            _write_text(left / "old.csv", "id,value\n3,delete\n2,same\n")
            _write_text(right / "new.csv", "id,value\n1,insert\n2,same\n")
            config = replace(load_app_config(), update_compare_keys={"new": ("id",), "old": ("id",)})
            pairs = [{"left_name": "old.csv", "right_name": "new.csv"}]
            separate = compare_csv_folder_pairs(left, right, root / "out", pairs, config=config)
            merged = compare_csv_folder_pairs_to_workbook(left, right, root / "merged.xlsx", pairs, config=config)
            (left / "old.csv").rename(left / "new.csv")
            recursive = compare_csv_folders(left, right, root / "recursive.xlsx", config=config)
            for result in (separate, merged, recursive):
                self.assertEqual(result.warnings, [])
                workbook = load_workbook(result.output_paths[0])
                try:
                    self.assertEqual([workbook.active.cell(3, col).value for col in range(3, 9)], [None, "1", "2", "2", "3", None])
                finally:
                    workbook.close()

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
            workbook.close()

            apply_fixme_replacements(entries, {0: "LATEST_NOTE", 1: "SPEC_CHANGE"})
            workbook = load_workbook(workbook_path)
            try:
                self.assertEqual(workbook["table"]["H3"].value, "LATEST_NOTE")
                self.assertEqual(workbook["table"]["H4"].value, "SPEC_CHANGE")
            finally:
                workbook.close()

    def test_apply_fixme_replacements_overwrites_shared_cell_with_latest_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            _write_text(before / "table.csv", "id,name\n1,old\n2,only_before\n")
            _write_text(after / "table.csv", "id,name\n1,new\n")
            workbook_path = root / "compare.xlsx"
            result = write_compare_workbook_with_fixmes(before, after, workbook_path)
            entries = result.fixme_entries
            name_indices = {
                entry.record_number: index
                for index, entry in enumerate(entries)
                if entry.column_name == "name"
            }
            self.assertEqual(set(name_indices), {1, 2})
            self.assertEqual(entries[name_indices[1]].fixme_cell, entries[name_indices[2]].fixme_cell)

            apply_fixme_replacements(entries, {name_indices[1]: "NOTE_1", name_indices[2]: "NOTE_1"})
            workbook = load_workbook(workbook_path)
            try:
                self.assertEqual(workbook["table"][entries[name_indices[1]].fixme_cell].value, "NOTE_1")
            finally:
                workbook.close()

            apply_fixme_replacements(entries, {name_indices[1]: "NOTE_2", name_indices[2]: "NOTE_2"})
            workbook = load_workbook(workbook_path)
            try:
                self.assertEqual(workbook["table"][entries[name_indices[1]].fixme_cell].value, "NOTE_2")
            finally:
                workbook.close()

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
            self.assertTrue(all(sheet.sheet_view.zoomScale == 85 for sheet in workbook.worksheets))
            workbook.close()

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
            for output_path in summary.output_paths:
                workbook = load_workbook(output_path)
                try:
                    self.assertTrue(all(sheet.sheet_view.zoomScale == 85 for sheet in workbook.worksheets))
                finally:
                    workbook.close()

    def test_compare_csv_folder_pairs_can_export_one_workbook_named_from_right_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            _write_text(left / "customer_old.csv", "id,name\n1,A\n")
            _write_text(left / "order_old.csv", "id,total\n1,10\n")
            _write_text(right / "customer_new.csv", "id,name\n1,B\n")
            _write_text(right / "order_new.csv", "id,total\n1,20\n")
            output = root / "paired.xlsx"

            summary = compare_csv_folder_pairs_to_workbook(left, right, output, [
                {"left_name": "customer_old.csv", "right_name": "customer_new.csv"},
                {"left_name": "order_old.csv", "right_name": "order_new.csv"},
            ])

            self.assertEqual(summary.workbook_count, 1)
            self.assertEqual(summary.sheet_count, 2)
            workbook = load_workbook(output)
            try:
                self.assertEqual(workbook.sheetnames, ["customer_new", "order_new"])
                self.assertTrue(all(sheet.sheet_view.zoomScale == 85 for sheet in workbook.worksheets))
            finally:
                workbook.close()

    def test_compare_detects_line_endings_and_distinct_null_representations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            _write_text(before / "table.csv", 'id,text,nullish\r\n1,"line1\r\nline2",\r\n')
            _write_text(after / "table.csv", 'id,text,nullish\r\n1,"line1\nline2","NULL"\r\n')
            output = root / "compare.xlsx"
            before_bytes = (before / "table.csv").read_bytes()
            after_bytes = (after / "table.csv").read_bytes()

            result = write_compare_workbook_with_fixmes(before, after, output)

            self.assertEqual({entry.column_name for entry in result.fixme_entries}, {"text", "nullish"})
            text_entry = next(entry for entry in result.fixme_entries if entry.column_name == "text")
            self.assertEqual(text_entry.left_value, "line1\r\nline2")
            self.assertEqual(text_entry.right_value, "line1\nline2")
            workbook = load_workbook(output)
            try:
                worksheet = workbook["table"]
                self.assertEqual(worksheet["C4"].value, "line1\r\nline2")
                self.assertEqual(worksheet["D4"].value, "line1\nline2")
                self.assertTrue(all(cell.alignment.wrap_text is not True for row in worksheet for cell in row))
            finally:
                workbook.close()
            apply_fixme_replacements(result.fixme_entries, {0: "reviewed"})
            workbook = load_workbook(output)
            try:
                worksheet = workbook["table"]
                self.assertEqual(worksheet["C4"].value, "line1\r\nline2")
                self.assertEqual(worksheet["D4"].value, "line1\nline2")
                self.assertTrue(all(cell.alignment.wrap_text is not True for row in worksheet for cell in row))
            finally:
                workbook.close()
            self.assertEqual((before / "table.csv").read_bytes(), before_bytes)
            self.assertEqual((after / "table.csv").read_bytes(), after_bytes)

    def test_compare_rejects_values_excel_would_truncate_without_touching_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            value = "a" * 32768
            _write_text(before / "table.csv", f'id,text\r\n1,"{value}"\r\n')
            _write_text(after / "table.csv", 'id,text\r\n1,"short"\r\n')
            output = root / "compare.xlsx"
            original = [(path, path.read_bytes()) for path in (before / "table.csv", after / "table.csv")]

            with self.assertRaisesRegex(ValueError, "32767"):
                write_compare_workbook_with_fixmes(before, after, output)

            self.assertFalse(output.exists())
            for path, content in original:
                self.assertEqual(path.read_bytes(), content)

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
