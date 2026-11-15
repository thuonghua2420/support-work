from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from autocompare_tool.app_config import load_app_config
from autocompare_tool.compare_keys import (
    extract_all_compare_keys, extract_compare_keys, remove_compare_keys, save_compare_key,
)
from autocompare_tool.database_io import (
    DatabaseColumn, DatabaseConnectionSettings, OperationCancelledError, TableMetadata, TableNotFoundError,
    validate_connection_settings,
)
from autocompare_tool.dbeaver_csv import read_dbeaver_csv, write_dbeaver_csv
from autocompare_tool.web_app import AutoCompareWebApplication, CancelToken


class CompareKeyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "config.ini"
        self.prefix = b"# keep comment\r\n[folders]\r\ninput_dir = input\r\noutput_dir = output\r\nafter_htm_dir = after_htm\r\nafter_htc_dir = after_htc\r\n\r\n"
        self.suffix = b"[excel_headers]\r\n# keep spacing\r\nleft_column_title  =  BEFORE\r\n"
        self.path.write_bytes(self.prefix + b"[update_compare_keys]\r\nmanual = BusinessCode\r\n\r\n" + self.suffix)
        self.case = self.root / "UT01"
        self.settings = DatabaseConnectionSettings("SQL Server", "localhost", "sample", schema="dbo", trusted_connection=True)
        self.adapter = Mock()
        self.metadata = {}
        self.adapter.get_table.side_effect = self.get_table
        self.adapter.list_tables.side_effect = lambda _connection, _settings: sorted(self.metadata)
        self.patcher = patch("autocompare_tool.compare_keys.get_adapter", return_value=self.adapter)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def get_table(self, connection, settings, table):
        if table not in self.metadata:
            raise TableNotFoundError(table)
        return self.metadata[table]

    def csv(self, table, headers, rows=None):
        for folder in ("input", "output/after_htm", "output/after_htc"):
            write_dbeaver_csv(self.case / folder / f"{table}.csv", headers, rows or [])

    def table(self, name, keys):
        self.metadata[name] = TableMetadata("dbo", name, [
            DatabaseColumn(column, index, "varchar", is_primary_key=True)
            for index, column in enumerate(keys, 1)
        ])

    def test_extract_complete_keys_keep_existing_and_preserve_config_and_csvs(self):
        self.csv("orders", ["OrderNo", "LineNo", "value"], [["A", "1", None]])
        self.table("orders", ["ORDERNO", "LINENO"])
        self.csv("manual", ["BusinessCode"])
        originals = {p: p.read_bytes() for p in self.case.rglob("*.csv")}

        result = extract_compare_keys(self.root, self.settings, lambda _: None, config_path=self.path)

        self.assertEqual(result.update_compare_keys, {"manual": ("BusinessCode",), "orders": ("OrderNo", "LineNo")})
        self.assertEqual((result.saved_count, result.existing_count), (1, 1))
        self.assertTrue(self.path.read_bytes().startswith(self.prefix))
        self.assertTrue(self.path.read_bytes().endswith(self.suffix))
        self.assertEqual(load_app_config(self.path).update_compare_keys, result.update_compare_keys)
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})
        self.adapter.get_table.assert_called_once()
        self.adapter.connect.return_value.close.assert_called_once()
        self.adapter.connect.return_value.commit.assert_not_called()

        again = extract_compare_keys(self.root, self.settings, lambda _: None, config_path=self.path)
        self.assertEqual(again.saved_count, 0)
        self.assertEqual(again.existing_count, 2)

    def test_no_pk_missing_table_and_incomplete_composite_key_are_skipped(self):
        for table in ("no_pk", "missing", "partial"):
            self.csv(table, ["id"])
        self.table("no_pk", [])
        self.table("partial", ["id", "line"])
        original = self.path.read_bytes()
        result = extract_compare_keys(self.root, self.settings, lambda _: None, config_path=self.path)
        self.assertEqual(len(result.skipped), 3)
        self.assertEqual(result.saved_count, 0)
        self.assertEqual(self.path.read_bytes(), original)

    def test_folder_key_extraction_uses_custom_case_pattern(self):
        self.path.write_bytes(self.path.read_bytes().replace(b"[folders]\r\n", b"[folders]\r\ncase_pattern = Scenario*\r\n"))
        self.case = self.root / "Scenario01"
        self.csv("orders", ["Id"])
        self.table("orders", ["ID"])
        result = extract_compare_keys(self.root, self.settings, lambda _: None, config_path=self.path)
        self.assertEqual(result.update_compare_keys["orders"], ("Id",))

    def test_error_or_cancel_does_not_save_partial_keys_and_closes_connection(self):
        self.csv("a", ["id"])
        self.csv("b", ["id"])
        self.table("a", ["id"])
        original = self.path.read_bytes()
        for error in (RuntimeError("metadata query failed"), OperationCancelledError("cancelled")):
            with self.subTest(error=error):
                self.adapter.get_table.side_effect = [self.metadata["a"], error]
                with self.assertRaises(type(error)):
                    extract_compare_keys(self.root, self.settings, lambda _: None, config_path=self.path)
                self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.adapter.connect.return_value.close.call_count, 2)

    def test_clear_only_keys_and_repeat_is_noop(self):
        result = remove_compare_keys(lambda _: None, config_path=self.path)
        self.assertEqual(result.removed_count, 1)
        self.assertEqual(load_app_config(self.path).update_compare_keys, {})
        self.assertTrue(self.path.read_bytes().startswith(self.prefix))
        self.assertTrue(self.path.read_bytes().endswith(self.suffix))
        original = self.path.read_bytes()
        self.assertEqual(remove_compare_keys(lambda _: None, config_path=self.path).removed_count, 0)
        self.assertEqual(self.path.read_bytes(), original)

    def test_extract_all_keys_from_connected_database_only_adds_keys(self):
        self.table("orders", ["OrderNo", "LineNo"])
        self.table("customers", ["CustomerId"])
        self.metadata["audit"] = TableMetadata("dbo", "audit", [
            DatabaseColumn("created_at", 1, "datetime", is_primary_key=False),
        ])

        result = extract_all_compare_keys(self.settings, lambda _: None, config_path=self.path)

        self.assertEqual(result.update_compare_keys, {
            "manual": ("BusinessCode",),
            "customers": ("CustomerId",),
            "orders": ("OrderNo", "LineNo"),
        })
        self.assertEqual((result.saved_count, result.existing_count, len(result.skipped)), (2, 0, 1))
        self.assertEqual(load_app_config(self.path).update_compare_keys, result.update_compare_keys)
        self.adapter.list_tables.assert_called_once()
        self.metadata.clear()
        self.table("invoices", ["InvoiceId"])
        second = extract_all_compare_keys(self.settings, lambda _: None, config_path=self.path)
        self.assertEqual(second.update_compare_keys, {
            **result.update_compare_keys, "invoices": ("InvoiceId",),
        })
        self.assertEqual(second.saved_count, 1)
        self.assertTrue(self.path.read_bytes().startswith(self.prefix))
        self.assertTrue(self.path.read_bytes().endswith(self.suffix))

    def test_extract_all_conflicts_keep_stored_key_and_report_warning(self):
        self.table("manual", ["DatabaseId"])
        self.table("orders", ["OrderId"])
        log = Mock()
        result = extract_all_compare_keys(self.settings, log, config_path=self.path)
        self.assertEqual(result.update_compare_keys, {
            "manual": ("BusinessCode",), "orders": ("OrderId",),
        })
        self.assertEqual((result.saved_count, result.existing_count), (1, 0))
        self.assertEqual(len(result.skipped), 1)
        self.assertIn("[manual] Conflict:", result.skipped[0])
        self.assertIn("BusinessCode", result.skipped[0])
        self.assertIn("DatabaseId", result.skipped[0])
        log.assert_any_call(result.skipped[0])
        log.assert_called_with("Added 1 tables; kept 0; conflicts 1; skipped 0.")
        self.assertEqual(load_app_config(self.path).update_compare_keys, result.update_compare_keys)

    def test_extract_all_without_additions_never_writes_config(self):
        for keys, expected_existing, expected_skipped in (
            (["BusinessCode"], 1, 0), (["OtherId"], 0, 1), ([], 0, 1),
        ):
            with self.subTest(keys=keys):
                self.table("manual", keys)
                original = self.path.read_bytes()
                mtime = self.path.stat().st_mtime_ns
                with patch("autocompare_tool.compare_keys._write_keys") as write:
                    result = extract_all_compare_keys(self.settings, lambda _: None, config_path=self.path)
                write.assert_not_called()
                self.assertEqual(result.saved_count, 0)
                self.assertEqual(result.existing_count, expected_existing)
                self.assertEqual(len(result.skipped), expected_skipped)
                self.assertEqual(result.update_compare_keys, {"manual": ("BusinessCode",)})
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.path.stat().st_mtime_ns, mtime)

    def test_extract_all_reloads_keys_after_metadata_queries(self):
        self.table("orders", ["OrderId"])

        def concurrent_edit():
            save_compare_key("orders", ["ManualOrderId"], self.path)
            save_compare_key("other", ["OtherId"], self.path)

        self.adapter.connect.return_value.close.side_effect = concurrent_edit
        result = extract_all_compare_keys(self.settings, lambda _: None, config_path=self.path)
        self.assertEqual(result.update_compare_keys, {
            "manual": ("BusinessCode",), "orders": ("ManualOrderId",), "other": ("OtherId",),
        })
        self.assertEqual(result.saved_count, 0)
        self.assertIn("Conflict:", result.skipped[0])

    def test_extract_all_error_or_cancel_never_saves_partial_keys(self):
        self.table("a", ["Id"])
        self.table("b", ["Id"])
        original = self.path.read_bytes()
        for error in (RuntimeError("metadata query failed"), OperationCancelledError("cancelled")):
            with self.subTest(error=error):
                self.adapter.get_table.side_effect = [self.metadata["a"], error]
                with self.assertRaises(type(error)):
                    extract_all_compare_keys(self.settings, lambda _: None, config_path=self.path)
                self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.adapter.connect.return_value.close.call_count, 2)

    def test_extract_all_cancellation_before_merge_never_writes(self):
        self.table("a", ["Id"])
        original = self.path.read_bytes()
        cancel = Mock(side_effect=[None, None, OperationCancelledError("cancelled")])
        with self.assertRaises(OperationCancelledError):
            extract_all_compare_keys(self.settings, lambda _: None, config_path=self.path, cancel=cancel)
        self.assertEqual(self.path.read_bytes(), original)
        self.adapter.connect.return_value.close.assert_called_once()

    def test_save_new_key_trims_and_casefolds_table_and_preserves_config(self):
        result = save_compare_key("  Orders  ", [" OrderNo ", " LineNo "], self.path)
        self.assertEqual(result.saved_count, 1)
        self.assertEqual(result.update_compare_keys, {
            "manual": ("BusinessCode",), "orders": ("OrderNo", "LineNo"),
        })
        self.assertEqual(load_app_config(self.path).update_compare_keys, result.update_compare_keys)
        self.assertTrue(self.path.read_bytes().startswith(self.prefix))
        self.assertTrue(self.path.read_bytes().endswith(self.suffix))
        self.assertNotIn(b"\n", self.path.read_bytes().replace(b"\r\n", b""))

    def test_save_existing_key_updates_only_selected_table(self):
        save_compare_key("orders", ["OrderId"], self.path)
        result = save_compare_key("MANUAL", ["NewCode", "Version"], self.path)
        self.assertEqual(result.update_compare_keys, {
            "manual": ("NewCode", "Version"), "orders": ("OrderId",),
        })
        self.assertEqual(load_app_config(self.path).update_compare_keys, result.update_compare_keys)
        self.assertTrue(self.path.read_bytes().startswith(self.prefix))
        self.assertTrue(self.path.read_bytes().endswith(self.suffix))

    def test_save_rejects_invalid_names_and_columns_without_writing(self):
        invalid_tables = [None, 1, "", "  ", "#table", ";table", " #table "]
        invalid_tables += [f"a{char}b" for char in "\r\n=:[]"]
        invalid_columns = [None, "Id", [], [""], [" "], [None], [1], ["Id", " id "],
                           ["Id", "Id"], ["a,b"], ["a\nb"], ["a\rb"], ["Id\n"]]
        original = self.path.read_bytes()
        for table, columns in ([(table, ["Id"]) for table in invalid_tables]
                               + [("orders", columns) for columns in invalid_columns]):
            with self.subTest(table=table, columns=columns):
                with self.assertRaises(ValueError):
                    save_compare_key(table, columns, self.path)
                self.assertEqual(self.path.read_bytes(), original)

    def test_api_save_requires_string_table_and_list_of_strings(self):
        app = AutoCompareWebApplication()
        for payload in ({}, {"table": "orders"}, {"columns": ["Id"]},
                        {"table": 1, "columns": ["Id"]}, {"table": None, "columns": ["Id"]},
                        {"table": "orders", "columns": "Id"}, {"table": "orders", "columns": None},
                        {"table": "orders", "columns": [1]}):
            with self.subTest(payload=payload), patch.object(app.jobs, "start") as start:
                with self.assertRaises(ValueError):
                    app.start_action("compare_keys_save", payload)
                start.assert_not_called()
        self.assertNotIn("compare_keys_save", app.CONFIRMED_ACTIONS)
        with patch.object(app.jobs, "start") as start:
            app.start_action("compare_keys_save", {"table": "orders", "columns": ["Id"]})
            start.assert_called_once()
        with patch("autocompare_tool.compare_keys.default_config_path", return_value=self.path):
            result = app._operation("compare_keys_save", {"table": "Orders", "columns": [" Id "]})(
                lambda _: None, CancelToken(),
            )
        self.assertEqual(result["update_compare_keys"], {"manual": ("BusinessCode",), "orders": ("Id",)})
        self.assertEqual(result["saved_count"], 1)

    def test_api_requires_connected_role_and_clear_confirmation(self):
        app = AutoCompareWebApplication()
        with self.assertRaisesRegex(ValueError, "Database"):
            app.start_action("compare_keys_extract", {"role": "unknown"})
        with self.assertRaisesRegex(ValueError, "database"):
            app.start_action("compare_keys_extract", {"role": "main"})
        with self.assertRaises(PermissionError):
            app.start_action("compare_keys_remove", {})

    def test_extracted_key_is_used_by_next_compare_without_dropping_records(self):
        self.csv("customers", ["CustomerId", "value"], [
            ["C001", "same"], ["C002", "same"], ["C004", "new"],
        ])
        source = self.case / "input/customers.csv"
        write_dbeaver_csv(source, ["CustomerId", "value"], [
            ["C001", "same"], ["C002", "same"], ["C003", "outside"], ["C004", "old"],
        ])
        self.table("customers", ["CustomerId"])
        originals = {p: p.read_bytes() for p in self.case.rglob("*.csv")}
        with patch("autocompare_tool.app_config.default_config_path", return_value=self.path), \
             patch("autocompare_tool.compare_keys.default_config_path", return_value=self.path):
            app = AutoCompareWebApplication()
            app._db_connection_cache["target"] = self.settings
            result = app._operation("compare_keys_extract", {"role": "target"})(lambda _: None, CancelToken())
            self.assertEqual(result["saved_count"], 1)
            self.adapter.connect.assert_called_with(validate_connection_settings(self.settings))
            summary = app._compare({
                "root": str(self.root),
                "workflows": ["htm_before_after", "htc_before_after", "after_htc_vs_htm"],
                "copy_input": True,
                "sort_by_key": True,
            }, lambda _: None)
            self.assertEqual((summary["workbook_count"], summary["error_count"]), (3, 0))
            config = load_app_config(self.path)
            for name in (config.folders.before_htm_dir, config.folders.before_htc_dir):
                before = self.case / "output" / name / "customers.csv"
                self.assertEqual([row[0] for row in read_dbeaver_csv(before).rows], ["C001", "C002", "C003", "C004"])
            self.assertEqual(originals, {p: p.read_bytes() for p in originals})
            app._operation("compare_keys_remove", {"confirmed": True})(lambda _: None, CancelToken())
            self.assertEqual(app.bootstrap(8765)["update_compare_keys"], {})


if __name__ == "__main__":
    unittest.main()
