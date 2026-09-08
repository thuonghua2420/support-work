from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from autocompare_tool.app_config import load_app_config
from autocompare_tool.dbeaver_csv import read_dbeaver_csv, write_dbeaver_csv
from autocompare_tool.update_compare import filter_update_before_folder


class UpdateCompareTests(unittest.TestCase):
    def test_workbooks_align_customers_and_only_force_order_for_validated_files(self):
        from openpyxl import load_workbook
        from autocompare_tool.processor import process_root

        for customer_keys in ({}, {"customers": ("missing",)}, {"customers": ("id",)}):
            with self.subTest(keys=customer_keys), tempfile.TemporaryDirectory() as temporary:
                config = replace(load_app_config(), update_compare_keys={"orders": ("code",), **customer_keys})
                case = Path(temporary) / "UT01"
                folders = config.folders
                output = case / folders.output_dir
                source = case / folders.input_dir
                write_dbeaver_csv(source / "customers.csv", ["id", "name"], [
                    ["C001", "An"], ["C002", "Binh"], ["C003", "Chau"], ["C004", "Dung"],
                ])
                write_dbeaver_csv(source / "orders.csv", ["id", "code"], [["1", "A"], ["2", "B"]])
                for after_name in (folders.after_htm_dir, folders.after_htc_dir):
                    write_dbeaver_csv(output / after_name / "customers.csv", ["id", "name"], [
                        ["C001", "An"], ["C002", "Binh"], ["C004", "Dung"],
                    ])
                    write_dbeaver_csv(output / after_name / "orders.csv", ["id", "code"], [
                        ["1", "B"], ["2", "A"],
                    ])
                originals = {path: path.read_bytes() for path in case.rglob("*.csv")}

                summary = process_root(case, config=config)

                self.assertFalse(summary.errors)
                self.assertEqual(len(summary.test_cases[0].workbooks), 3)
                for result in summary.test_cases[0].workbooks:
                    workbook = load_workbook(result.output_path)
                    try:
                        if result.workflow_key in {"htm_before_after", "htc_before_after"}:
                            orders = workbook["orders"]
                            self.assertEqual((orders["C4"].value, orders["D4"].value), ("B", "B"))
                            self.assertEqual((orders["E4"].value, orders["F4"].value), ("A", "A"))
                            if customer_keys == {"customers": ("id",)}:
                                self.assertNotIn("customers", workbook.sheetnames)
                            else:
                                sheet = workbook["customers"]
                                self.assertEqual((sheet["G3"].value, sheet["H3"].value), ("C004", "C004"))
                                self.assertEqual((sheet["I3"].value, sheet["J3"].value), ("C003", None))
                        else:
                            sheet = workbook["customers"]
                            self.assertEqual((sheet["G3"].value, sheet["H3"].value), ("C004", "C004"))
                    finally:
                        workbook.close()
                for before_name in (folders.before_htm_dir, folders.before_htc_dir):
                    customer_csv = output / before_name / "customers.csv"
                    if customer_keys == {"customers": ("id",)}:
                        self.assertFalse(customer_csv.exists())
                    else:
                        rows = read_dbeaver_csv(customer_csv).rows
                        self.assertEqual([row[0] for row in rows], ["C001", "C002", "C003", "C004"])
                self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_composite_key_filters_disk_in_after_order_preserving_nulls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, after = root / "before", root / "after"
            headers = ["id", "order", "line", "value"]
            write_dbeaver_csv(before / "orders.csv", headers, [
                ["1", "A", "1", None], ["2", "A", "2", ""], ["3", "B", "1", "extra"],
            ])
            write_dbeaver_csv(after / "orders.csv", headers, [
                ["20", "A", "2", "updated"], ["10", "A", "1", "updated"],
            ])
            original_after = (after / "orders.csv").read_bytes()
            logs = []
            filter_update_before_folder(before, after, {"orders": ("order", "line")}, logs.append)
            self.assertEqual(read_dbeaver_csv(before / "orders.csv").rows,
                             [["2", "A", "2", ""], ["1", "A", "1", None]])
            self.assertEqual((after / "orders.csv").read_bytes(), original_after)
            self.assertIn("removed delete records=[3]", logs[0])

    def test_filter_removes_insert_and_delete_records_from_opposite_sides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, after = root / "before", root / "after"
            headers = ["id", "value", "nullable"]
            write_dbeaver_csv(before / "mixed.csv", headers, [
                ["A", "old-A", None], ["B", "same-B", ""], ["D", "deleted", "x"],
            ])
            write_dbeaver_csv(after / "mixed.csv", headers, [
                ["B", "same-B", ""], ["A", "new-A", None], ["C", "inserted", "y"],
            ])
            logs = []

            aligned = filter_update_before_folder(before, after, {"mixed": ("id",)}, logs.append)

            self.assertEqual(aligned, {before / "mixed.csv"})
            self.assertEqual(read_dbeaver_csv(before / "mixed.csv").rows, [
                ["B", "same-B", ""], ["A", "old-A", None],
            ])
            self.assertEqual(read_dbeaver_csv(after / "mixed.csv").rows, [
                ["B", "same-B", ""], ["A", "new-A", None],
            ])
            self.assertIn("removed delete records=[3]", logs[0])
            self.assertIn("removed insert records=[3]", logs[0])

    def test_invalid_mapping_preserves_every_before_file(self):
        scenarios = [
            (["id"], [["1"], ["1"]], [["1"]], {"bad": ("id",)}),
            (["id"], [["1"]], [["1"], ["1"]], {"bad": ("id",)}),
            (["id"], [[None]], [["1"]], {"bad": ("id",)}),
            (["id"], [["1"]], [[""]], {"bad": ("id",)}),
            (["id"], [["1"]], [["1"]], {}),
            (["id"], [["1"]], [["1"]], {"bad": ("missing",)}),
            (["id", "id"], [["1", "2"]], [["1", "2"]], {"bad": ("id",)}),
        ]
        for headers, before_rows, after_rows, keys in scenarios:
            with self.subTest(before=before_rows, after=after_rows, keys=keys):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    before, after = root / "before", root / "after"
                    write_dbeaver_csv(before / "aaa.csv", ["id"], [["1"], ["2"]])
                    write_dbeaver_csv(after / "aaa.csv", ["id"], [["2"]])
                    write_dbeaver_csv(before / "bad.csv", headers, before_rows)
                    write_dbeaver_csv(after / "bad.csv", headers, after_rows)
                    originals = {path: path.read_bytes() for path in before.glob("*.csv")}
                    with self.assertRaises(ValueError):
                        filter_update_before_folder(before, after, {"aaa": ("id",), **keys}, lambda _: None)
                    self.assertEqual({path: path.read_bytes() for path in originals}, originals)
                    self.assertFalse(list(before.glob("*.tmp")))

    def test_missing_after_folder_or_csv_and_missing_before_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, after = root / "before", root / "after"
            write_dbeaver_csv(before / "orders.csv", ["id"], [["1"], ["2"]])
            original = (before / "orders.csv").read_bytes()
            with self.assertRaisesRegex(ValueError, "Missing after folder"):
                filter_update_before_folder(before, after, {"orders": ("id",)}, lambda _: None)
            after.mkdir()
            with self.assertRaisesRegex(ValueError, "No after CSV"):
                filter_update_before_folder(before, after, {"orders": ("id",)}, lambda _: None)
            write_dbeaver_csv(after / "missing.csv", ["id"], [["1"]])
            with self.assertRaisesRegex(ValueError, "missing before CSV"):
                filter_update_before_folder(before, after, {"missing": ("id",)}, lambda _: None)
            self.assertEqual((before / "orders.csv").read_bytes(), original)

    def test_config_loads_exact_composite_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.ini"
            path.write_text("[update_compare_keys]\nORDERS = OrderNo, LineNo\n", encoding="utf-8")
            self.assertEqual(load_app_config(path).update_compare_keys, {"orders": ("OrderNo", "LineNo")})

    def test_non_strict_missing_key_keeps_before_file_for_compare(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, after = root / "before", root / "after"
            write_dbeaver_csv(before / "orders.csv", ["id", "name"], [["1", "old"], ["2", "outside"]])
            write_dbeaver_csv(after / "orders.csv", ["id", "name"], [["9", "new"]])
            original_before = (before / "orders.csv").read_bytes()
            logs = []

            filter_update_before_folder(before, after, {}, logs.append, strict=False)

            self.assertEqual((before / "orders.csv").read_bytes(), original_before)
            self.assertIn("kept unchanged", logs[0])

    def test_process_filters_systems_independently_and_keeps_sources(self):
        try:
            from autocompare_tool.processor import process_root
        except ImportError:
            self.skipTest("openpyxl is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(load_app_config(), update_compare_keys={"orders": ("code",)})
            case = Path(temporary) / "UT01"
            folders = config.folders
            source = case / folders.input_dir / "orders.csv"
            output = case / folders.output_dir
            after_htm = output / folders.after_htm_dir / "orders.csv"
            after_htc = output / folders.after_htc_dir / "orders.csv"
            write_dbeaver_csv(source, ["id", "code", "value"], [
                ["1", "A", "old-A"], ["2", "B", "old-B"], ["3", "C", "old-C"],
            ])
            write_dbeaver_csv(after_htm, ["id", "code", "value"], [["1", "B", "new-B"]])
            write_dbeaver_csv(after_htc, ["id", "code", "value"], [["4", "C", "new-C"]])
            originals = {path: path.read_bytes() for path in (source, after_htm, after_htc)}
            for _ in range(2):
                summary = process_root(case, config=config)
                self.assertFalse(summary.errors)
                self.assertEqual(read_dbeaver_csv(output / folders.before_htm_dir / "orders.csv").rows,
                                 [["2", "B", "old-B"]])
                self.assertEqual(read_dbeaver_csv(output / folders.before_htc_dir / "orders.csv").rows,
                                 [["3", "C", "old-C"]])
                self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_process_filters_disjoint_insert_delete_sets_and_still_creates_workbooks(self):
        try:
            from autocompare_tool.processor import process_root
        except ImportError:
            self.skipTest("openpyxl is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(load_app_config(), update_compare_keys={"orders": ("id",)})
            case = Path(temporary) / "UT01"
            folders = config.folders
            output = case / folders.output_dir
            write_dbeaver_csv(case / folders.input_dir / "orders.csv", ["id"], [["1"], ["2"]])
            write_dbeaver_csv(output / folders.after_htm_dir / "orders.csv", ["id"], [["9"]])
            write_dbeaver_csv(output / folders.after_htc_dir / "orders.csv", ["id"], [["2"]])
            stale = output / folders.compare_dir / config.workbooks.htm_before_after_file
            stale.parent.mkdir(parents=True)
            stale.write_bytes(b"old workbook")
            summary = process_root(case, config=config)
            self.assertFalse(summary.errors)
            self.assertEqual(len(summary.test_cases[0].workbooks), 3)
            self.assertTrue(stale.exists())
            self.assertFalse((output / folders.before_htm_dir).exists())
            self.assertFalse((output / folders.before_htc_dir).exists())
            self.assertEqual(read_dbeaver_csv(output / folders.after_htm_dir / "orders.csv").rows, [])
            self.assertEqual(read_dbeaver_csv(output / folders.after_htc_dir / "orders.csv").rows, [["2"]])

    def test_process_creates_all_selected_workbooks_when_update_keys_are_missing(self):
        try:
            from autocompare_tool.processor import process_root
        except ImportError:
            self.skipTest("openpyxl is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(load_app_config(), update_compare_keys={})
            case = Path(temporary) / "UT01"
            folders = config.folders
            output = case / folders.output_dir
            write_dbeaver_csv(case / folders.input_dir / "orders.csv", ["id", "name"], [["1", "old"], ["2", "outside"]])
            write_dbeaver_csv(output / folders.after_htm_dir / "orders.csv", ["id", "name"], [["9", "new"]])
            write_dbeaver_csv(output / folders.after_htc_dir / "orders.csv", ["id", "name"], [["8", "current"]])

            summary = process_root(case, config=config)

            self.assertFalse(summary.errors)
            self.assertEqual(len(summary.test_cases[0].workbooks), 3)
            self.assertTrue((output / folders.compare_dir / config.workbooks.htm_before_after_file).exists())
            self.assertTrue((output / folders.compare_dir / config.workbooks.htc_before_after_file).exists())
            self.assertTrue((output / folders.compare_dir / config.workbooks.after_htc_vs_htm_file).exists())
            self.assertEqual(read_dbeaver_csv(output / folders.before_htm_dir / "orders.csv").rows,
                             [["1", "old"], ["2", "outside"]])

    def test_process_prunes_insert_delete_rows_and_removes_equal_sheets_and_before_csvs(self):
        from openpyxl import load_workbook
        from autocompare_tool.processor import process_root

        with tempfile.TemporaryDirectory() as temporary:
            config = replace(load_app_config(), update_compare_keys={
                "inserted": ("id",), "deleted": ("id",), "equal": ("id",),
            })
            case = Path(temporary) / "UT01"
            folders = config.folders
            source = case / folders.input_dir
            output = case / folders.output_dir
            write_dbeaver_csv(source / "inserted.csv", ["id", "value"], [["A", "old"]])
            write_dbeaver_csv(source / "deleted.csv", ["id", "value"], [["D", "old"], ["X", "deleted"]])
            write_dbeaver_csv(source / "equal.csv", ["id", "value"], [["E", "same"]])
            original_source = {path: path.read_bytes() for path in source.glob("*.csv")}
            for after_name in (folders.after_htm_dir, folders.after_htc_dir):
                write_dbeaver_csv(output / after_name / "inserted.csv", ["id", "value"], [
                    ["A", "new"], ["N", "inserted"],
                ])
                write_dbeaver_csv(output / after_name / "deleted.csv", ["id", "value"], [["D", "new"]])
                write_dbeaver_csv(output / after_name / "equal.csv", ["id", "value"], [["E", "same"]])

            summary = process_root(case, config=config)

            self.assertFalse(summary.errors)
            by_workflow = {item.workflow_key: item for item in summary.test_cases[0].workbooks}
            for workflow_key in ("htm_before_after", "htc_before_after"):
                result = by_workflow[workflow_key]
                self.assertEqual(result.sheet_count, 2)
                self.assertEqual({path.name for path in result.removed_equal_before_files}, {"equal.csv"})
                workbook = load_workbook(result.output_path)
                try:
                    self.assertEqual(set(workbook.sheetnames), {"inserted", "deleted"})
                finally:
                    workbook.close()
            for before_name in (folders.before_htm_dir, folders.before_htc_dir):
                before_dir = output / before_name
                self.assertEqual({path.name for path in before_dir.glob("*.csv")}, {"inserted.csv", "deleted.csv"})
                self.assertEqual(read_dbeaver_csv(before_dir / "inserted.csv").rows, [["A", "old"]])
                self.assertEqual(read_dbeaver_csv(before_dir / "deleted.csv").rows, [["D", "old"]])
            for after_name in (folders.after_htm_dir, folders.after_htc_dir):
                self.assertEqual(read_dbeaver_csv(output / after_name / "inserted.csv").rows, [["A", "new"]])
                self.assertEqual(read_dbeaver_csv(output / after_name / "deleted.csv").rows, [["D", "new"]])
                self.assertEqual(read_dbeaver_csv(output / after_name / "equal.csv").rows, [["E", "same"]])
            self.assertEqual(original_source, {path: path.read_bytes() for path in original_source})

    def test_process_removes_empty_before_folders_when_all_sheets_are_equal(self):
        from openpyxl import load_workbook
        from autocompare_tool.processor import process_root

        with tempfile.TemporaryDirectory() as temporary:
            config = replace(load_app_config(), update_compare_keys={"equal": ("id",)})
            case = Path(temporary) / "UT01"
            folders = config.folders
            output = case / folders.output_dir
            write_dbeaver_csv(case / folders.input_dir / "equal.csv", ["id", "value"], [["E", "same"]])
            for after_name in (folders.after_htm_dir, folders.after_htc_dir):
                write_dbeaver_csv(output / after_name / "equal.csv", ["id", "value"], [["E", "same"]])

            summary = process_root(case, config=config)

            self.assertFalse(summary.errors)
            by_workflow = {item.workflow_key: item for item in summary.test_cases[0].workbooks}
            for workflow_key in ("htm_before_after", "htc_before_after"):
                result = by_workflow[workflow_key]
                self.assertEqual(result.sheet_count, 0)
                workbook = load_workbook(result.output_path)
                try:
                    self.assertEqual(workbook.sheetnames, ["Summary"])
                finally:
                    workbook.close()
            self.assertFalse((output / folders.before_htm_dir).exists())
            self.assertFalse((output / folders.before_htc_dir).exists())


if __name__ == "__main__":
    unittest.main()
