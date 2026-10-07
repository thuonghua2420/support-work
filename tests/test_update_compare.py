from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

from openpyxl import load_workbook

from autocompare_tool.app_config import load_app_config
from autocompare_tool.csv_order import sort_csv_folders_by_key
from autocompare_tool.dbeaver_csv import read_dbeaver_csv, write_dbeaver_csv
from autocompare_tool.processor import process_root


class CompareFileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.case = Path(self.temporary.name) / "UT01"
        self.config = replace(load_app_config(), update_compare_keys={"orders": ("code", "line")},
                              copy_input_default=False, sort_by_key_default=False)
        self.folders = self.config.folders
        self.output = self.case / self.folders.output_dir
        self.headers = ["id", "code", "line", "value"]
        self.before_rows = [["1", "B", "1", None], ["2", "A", "2", ""], ["3", "A", "1", "old"]]
        self.after_rows = [["30", "A", "1", "new"], ["40", "C", "1", "insert"], ["20", "A", "2", ""]]
        for name in (self.folders.before_htm_dir, self.folders.before_htc_dir):
            write_dbeaver_csv(self.output / name / "orders.csv", self.headers, self.before_rows)
        for name in (self.folders.after_htm_dir, self.folders.after_htc_dir):
            write_dbeaver_csv(self.output / name / "orders.csv", self.headers, self.after_rows)

    def snapshot(self):
        return {path: path.read_bytes() for path in self.case.rglob("*.csv")}

    def test_default_compare_needs_no_input_and_changes_no_csv(self):
        original = self.snapshot()
        result = process_root(self.case, config=self.config)
        self.assertFalse(result.errors)
        self.assertEqual(len(result.test_cases[0].workbooks), 3)
        self.assertEqual(result.test_cases[0].copied_files, 0)
        self.assertEqual(self.snapshot(), original)
        self.assertFalse((self.case / self.folders.input_dir).exists())

    def test_sheet_zoom_applies_to_every_generated_sheet(self):
        result = process_root(self.case, config=self.config, sheet_zoom=75)
        self.assertFalse(result.errors)
        for generated in result.test_cases[0].workbooks:
            workbook = load_workbook(generated.output_path)
            try:
                self.assertTrue(workbook.worksheets)
                self.assertTrue(all(sheet.sheet_view.zoomScale == 75 for sheet in workbook.worksheets))
            finally:
                workbook.close()

    def test_invalid_sheet_zoom_does_not_modify_csv(self):
        original = self.snapshot()
        for zoom in (0, 401, 75.5, "abc"):
            with self.subTest(zoom=zoom), self.assertRaises(ValueError):
                process_root(self.case, config=self.config, sheet_zoom=zoom)
        self.assertEqual(self.snapshot(), original)

    def test_copy_is_explicit_and_overwrites_without_clearing_before(self):
        source = self.case / self.folders.input_dir / "orders.csv"
        write_dbeaver_csv(source, self.headers, [["9", "X", "1", "input"]])
        before = self.output / self.folders.before_htm_dir
        write_dbeaver_csv(before / "manual.csv", ["id"], [["manual"]])
        original = self.snapshot()
        result = process_root(self.case, config=self.config, selected_workflow_keys={"htm_before_after"}, copy_input=False)
        self.assertFalse(result.errors)
        self.assertEqual(self.snapshot(), original)
        result = process_root(self.case, config=self.config, selected_workflow_keys={"htm_before_after"}, copy_input=True)
        self.assertFalse(result.errors)
        self.assertEqual((self.output / self.folders.before_htm_dir / "orders.csv").read_bytes(), source.read_bytes())
        self.assertEqual(
            (self.output / self.folders.before_htc_dir / "orders.csv").read_bytes(),
            original[self.output / self.folders.before_htc_dir / "orders.csv"],
        )
        for path, content in original.items():
            if path.parent.name not in (self.folders.before_htm_dir, self.folders.before_htc_dir) or path.name == "manual.csv":
                self.assertEqual(path.read_bytes(), content)

    def test_after_only_ignores_copy_checkbox_without_input_or_before(self):
        for name in (self.folders.before_htm_dir, self.folders.before_htc_dir):
            (self.output / name / "orders.csv").unlink()
            (self.output / name).rmdir()
        original = self.snapshot()
        result = process_root(self.case, config=self.config, selected_workflow_keys={"after_htc_vs_htm"}, copy_input=True)
        self.assertFalse(result.errors)
        self.assertEqual(self.snapshot(), original)
        self.assertFalse((self.output / self.folders.before_htm_dir).exists())
        self.assertFalse((self.output / self.folders.before_htc_dir).exists())

    def test_sort_writes_both_sides_and_pairs_composite_keys_without_removing_records(self):
        original_rows = {path: Counter(map(tuple, read_dbeaver_csv(path).rows)) for path in self.snapshot()}
        result = process_root(self.case, config=self.config, sort_by_key=True)
        self.assertFalse(result.errors)
        for path, rows in original_rows.items():
            actual = read_dbeaver_csv(path).rows
            self.assertEqual(Counter(map(tuple, actual)), rows)
            self.assertEqual(actual, sorted(actual, key=lambda row: (row[1], row[2])))
        workbook = load_workbook(result.test_cases[0].workbooks[0].output_path)
        try:
            sheet = workbook["orders"]
            self.assertEqual((sheet["C3"].value, sheet["D3"].value), ("3", "30"))
            self.assertEqual((sheet["C4"].value, sheet["D4"].value), ("A", "A"))
            self.assertEqual((sheet["G4"].value, sheet["H4"].value), ("B", None))
            self.assertEqual((sheet["I4"].value, sheet["J4"].value), (None, "C"))
        finally:
            workbook.close()

    def test_copy_failure_does_not_block_after_after(self):
        original = self.snapshot()
        result = process_root(self.case, config=self.config, copy_input=True)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual([item.workflow_key for item in result.test_cases[0].workbooks], ["after_htc_vs_htm"])
        self.assertEqual(self.snapshot(), original)

    def test_copy_then_sort_preserves_input_and_all_after_records(self):
        source = self.case / self.folders.input_dir / "orders.csv"
        write_dbeaver_csv(source, self.headers, self.before_rows)
        original_source = source.read_bytes()
        result = process_root(self.case, config=self.config, copy_input=True, sort_by_key=True)
        self.assertFalse(result.errors)
        self.assertEqual(source.read_bytes(), original_source)
        for name in (self.folders.before_htm_dir, self.folders.before_htc_dir):
            rows = read_dbeaver_csv(self.output / name / "orders.csv").rows
            self.assertEqual(rows, sorted(self.before_rows, key=lambda row: (row[1], row[2])))
        for name in (self.folders.after_htm_dir, self.folders.after_htc_dir):
            rows = read_dbeaver_csv(self.output / name / "orders.csv").rows
            self.assertEqual(Counter(map(tuple, rows)), Counter(map(tuple, self.after_rows)))

    def test_equal_csv_and_before_only_tables_are_kept_after_only_tables_excluded(self):
        for name in (self.folders.before_htm_dir, self.folders.before_htc_dir,
                     self.folders.after_htm_dir, self.folders.after_htc_dir):
            write_dbeaver_csv(self.output / name / "equal.csv", ["id"], [["1"]])
        for name in (self.folders.after_htm_dir, self.folders.after_htc_dir):
            write_dbeaver_csv(self.output / name / "after_only.csv", ["id"], [["2"]])
        for name in (self.folders.before_htm_dir, self.folders.before_htc_dir):
            write_dbeaver_csv(self.output / name / "before_only.csv", ["id"], [["3"]])
        original = self.snapshot()
        result = process_root(self.case, config=self.config)
        self.assertFalse(result.errors)
        self.assertEqual(self.snapshot(), original)
        for item in result.test_cases[0].workbooks[:2]:
            workbook = load_workbook(item.output_path)
            try:
                self.assertEqual(set(workbook.sheetnames), {"orders", "equal", "before_only"})
            finally:
                workbook.close()

    def test_rerun_preserves_unselected_workbooks_and_failed_selected_output(self):
        first = process_root(self.case, config=self.config)
        original = {item.output_path: item.output_path.read_bytes() for item in first.test_cases[0].workbooks}
        second = process_root(self.case, config=self.config, selected_workflow_keys={"htm_before_after"})
        self.assertFalse(second.errors)
        self.assertEqual(len(second.test_cases[0].workbooks), 1)
        for path, content in original.items():
            if path.name != self.config.workbooks.htm_before_after_file:
                self.assertEqual(path.read_bytes(), content)
        target = self.output / self.folders.compare_dir / self.config.workbooks.htm_before_after_file
        previous = target.read_bytes()
        (self.output / self.folders.before_htm_dir / "orders.csv").unlink()
        (self.output / self.folders.before_htm_dir).rmdir()
        result = process_root(self.case, config=self.config)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.test_cases[0].workbooks), 2)
        self.assertEqual(target.read_bytes(), previous)

    def test_config_loads_checkbox_defaults(self):
        path = Path(self.temporary.name) / "config.ini"
        path.write_text("[compare_workflows]\ncopy_input_enabled=true\nsort_by_key_enabled=true\n"
                        "[update_compare_keys]\nORDERS = Code, Line\n", encoding="utf-8")
        config = load_app_config(path)
        self.assertTrue(config.copy_input_default)
        self.assertTrue(config.sort_by_key_default)
        self.assertEqual(config.update_compare_keys, {"orders": ("Code", "Line")})


class CsvOrderTests(unittest.TestCase):
    def test_order_preserves_raw_records_encoding_bom_and_multiline_values(self):
        for encoding in ("utf-8-sig", "cp932"):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "orders.csv"
                header = "ID,code,line,value\r\n"
                second = '1,B,1,"日本\r\n語"\r\n'
                first = '2,A,1,""\r\n'
                third = '3,C,1,\r\n'
                path.write_bytes((header + second + first + third).encode(encoding))
                keys = sort_csv_folders_by_key([path.parent], {"orders": ("CODE", "LINE")}, lambda _: None)
                self.assertEqual(keys, {"orders": ("CODE", "LINE")})
                self.assertEqual(path.read_bytes(), (header + first + second + third).encode(encoding))

    def test_invalid_key_on_either_side_leaves_both_files_untouched(self):
        for rows, keys in (([["1", "A"], ["2", "A"]], {"orders": ("code",)}),
                           ([["1", None]], {"orders": ("code",)}),
                           ([["1", ""]], {"orders": ("code",)}),
                           ([["1", "A"]], {"orders": ("missing",)}),
                           ([["1", "A"]], {})):
            with self.subTest(rows=rows, keys=keys), tempfile.TemporaryDirectory() as temporary:
                before, after = Path(temporary) / "before", Path(temporary) / "after"
                write_dbeaver_csv(before / "orders.csv", ["id", "code"], [["2", "B"], ["1", "A"]])
                write_dbeaver_csv(after / "orders.csv", ["id", "code"], rows)
                paths = [before / "orders.csv", after / "orders.csv"]
                originals = [path.read_bytes() for path in paths]
                logs = []
                self.assertEqual(sort_csv_folders_by_key([before, after], keys, logs.append), {})
                self.assertEqual([path.read_bytes() for path in paths], originals)
                self.assertIn("Skip ordering", logs[0])

    def test_order_keeps_last_record_without_final_newline_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "orders.csv"
            path.write_bytes(b"id,value\r\n2,last\r\n1,first")
            sort_csv_folders_by_key([path.parent], {"orders": ("id",)}, lambda _: None)
            self.assertEqual(read_dbeaver_csv(path).rows, [["1", "first"], ["2", "last"]])
