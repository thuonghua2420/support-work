from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from autocompare_tool.database_io import DatabaseConnectionSettings, DatabaseCsvSummary, DatabaseSyncSummary
from autocompare_tool.excel_format_presets import ExcelFormatPresetStore
from autocompare_tool.excel_image_formatter import ExcelImageFormatSummary
from autocompare_tool.excel_writer import WorkbookFixmeEntry
from autocompare_tool.sql_excel_loader import ExcelSqlEntry
from autocompare_tool.sql_tools import SqlFormatResult
from autocompare_tool.web_app import (
    AutoCompareWebApplication,
    JobManager,
    _db_settings,
    _fixme_to_dict,
)


class WebApplicationTests(unittest.TestCase):
    def test_bootstrap_contains_web_defaults_and_workflows(self) -> None:
        app = AutoCompareWebApplication()

        result = app.bootstrap(9876)

        self.assertEqual(9876, result["port"])
        self.assertEqual(str(Path.cwd()), result["cwd"])
        self.assertTrue(result["compare_workflows"])
        self.assertIn("SQL Server", result["database_types"])
        self.assertIn("folder_compare_file", result)
        self.assertIn("excel_format_presets", result)

    def test_excel_format_preset_can_be_saved_and_deleted(self) -> None:
        app = AutoCompareWebApplication()
        with tempfile.TemporaryDirectory() as temp_dir:
            app.excel_format_preset_store = ExcelFormatPresetStore(Path(temp_dir) / "presets.json")

            presets = app.save_excel_format_preset(
                {
                    "name": "UT chuẩn",
                    "font_name": "Meiryo UI",
                    "font_size": "10.5",
                    "exclusions": "Header\n(Title, B2)",
                }
            )

            self.assertEqual("UT chuẩn", presets[0]["name"])
            self.assertEqual(10.5, presets[0]["font_size"])
            self.assertEqual(["Header", "(Title, B2)"], presets[0]["exclusions"])
            self.assertEqual([], app.delete_excel_format_preset({"name": "UT chuẩn"}))

    def test_file_picker_filters_files_but_keeps_directories(self) -> None:
        app = AutoCompareWebApplication()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "report.xlsx").write_bytes(b"test")
            (root / "notes.txt").write_text("test", encoding="utf-8")

            result = app.list_files(str(root), "file", ["xlsx"])

        entries = {entry["name"]: entry for entry in result["entries"]}
        self.assertIn("nested", entries)
        self.assertTrue(entries["nested"]["is_dir"])
        self.assertIn("report.xlsx", entries)
        self.assertNotIn("notes.txt", entries)

    def test_file_picker_directory_mode_only_returns_directories(self) -> None:
        app = AutoCompareWebApplication()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "data.csv").write_text("id\n1\n", encoding="utf-8")

            result = app.list_files(str(root), "directory", [])

        self.assertEqual(["nested"], [entry["name"] for entry in result["entries"]])

    def test_fixme_snapshot_keeps_sheet_and_source_csv_names_separate(self) -> None:
        entry = WorkbookFixmeEntry(
            case_folder_name="UT01-001",
            workbook_path=Path("C:/work/Compare_Before_After.xlsx"),
            workbook_name="Compare_Before_After.xlsx",
            csv_file_name="nested/VeryLongTableName.csv",
            sheet_name="nested_VeryLongTableName",
            column_name="Amount",
            left_value="100",
            right_value="200",
            record_number=3,
            worksheet_row=8,
            fixme_column=12,
        )

        result = _fixme_to_dict(entry, 5)

        self.assertEqual(5, result["index"])
        self.assertEqual("Compare_Before_After.xlsx", result["workbook_name"])
        self.assertEqual("nested_VeryLongTableName", result["sheet_name"])
        self.assertEqual("nested/VeryLongTableName.csv", result["csv_file_name"])
        self.assertEqual("nested/VeryLongTableName", result["source_sheet_name"])
        self.assertEqual("L8", result["fixme_cell"])

    def test_destructive_action_requires_explicit_confirmation(self) -> None:
        app = AutoCompareWebApplication()

        with self.assertRaises(PermissionError):
            app.start_action("delete_empty_folders", {"root": str(Path.cwd())})

    def test_excel_format_action_requires_explicit_confirmation(self) -> None:
        app = AutoCompareWebApplication()

        with self.assertRaises(PermissionError):
            app.start_action("format_excel_images", {"root": str(Path.cwd())})

    def test_excel_format_action_maps_safe_copy_options(self) -> None:
        app = AutoCompareWebApplication()
        summary = ExcelImageFormatSummary(
            action_name="Format ảnh Excel",
            root_path=Path.cwd(),
            output_root=Path.cwd() / "Formatted",
        )
        payload = {
            "root": str(Path.cwd()),
            "recursive": False,
            "overwrite_original": False,
            "run_image_format": False,
            "font_name": "Calibri",
            "font_size": "12",
            "font_size_exclusions": "Header\n(Title, A1)",
        }

        with patch("autocompare_tool.web_app.format_excel_images", return_value=summary) as format_mock:
            result = app._operation("format_excel_images", payload)(lambda _message: None)

        self.assertEqual(0, result["processed_count"])
        self.assertEqual(str(Path.cwd() / "Formatted"), result["output_root"])
        self.assertFalse(format_mock.call_args.kwargs["recursive"])
        self.assertFalse(format_mock.call_args.kwargs["overwrite_original"])
        self.assertTrue(format_mock.call_args.kwargs["draw_format"])
        self.assertFalse(format_mock.call_args.kwargs["run_image_format"])
        self.assertEqual("Calibri", format_mock.call_args.kwargs["font_name"])
        self.assertEqual("12", format_mock.call_args.kwargs["font_size"])
        self.assertEqual("Header\n(Title, A1)", format_mock.call_args.kwargs["font_size_exclusions"])

    def test_sql_format_action_maps_sql_and_dialect(self) -> None:
        app = AutoCompareWebApplication()
        summary = SqlFormatResult(
            formatted_sql="SELECT\n  *\nFROM x",
            statement_count=1,
            dialect="tsql",
        )

        with patch("autocompare_tool.web_app.format_sql", return_value=summary) as format_mock:
            result = app._operation(
                "sql_format",
                {"sql": "select * from x", "dialect": "tsql"},
            )(lambda _message: None)

        self.assertEqual("SELECT\n  *\nFROM x", result["formatted_sql"])
        self.assertEqual("select * from x", format_mock.call_args.args[0])
        self.assertEqual("tsql", format_mock.call_args.kwargs["dialect"])
        self.assertIsNotNone(format_mock.call_args.kwargs["log"])

    def test_sql_load_excel_action_reads_entries_and_formats_numbered_sql(self) -> None:
        app = AutoCompareWebApplication()
        entries = [
            ExcelSqlEntry("1", "select * from customers", 5, 8),
            ExcelSqlEntry("2", "select * from orders", 9, 12),
        ]
        summary = SqlFormatResult(
            formatted_sql="-- SQL No.1\nSELECT * FROM customers;",
            statement_count=2,
            dialect="tsql",
        )

        with patch("autocompare_tool.web_app.load_sql_entries_from_excel", return_value=entries) as load_mock:
            with patch("autocompare_tool.web_app.format_excel_sql_entries", return_value=summary) as format_mock:
                result = app._operation(
                    "sql_load_excel",
                    {"excel_path": "input.xlsx", "sheet_name": "SQLList", "dialect": "tsql"},
                )(lambda _message: None)

        load_mock.assert_called_once_with("input.xlsx", "SQLList")
        self.assertEqual(entries, format_mock.call_args.args[0])
        self.assertEqual("tsql", format_mock.call_args.kwargs["dialect"])
        self.assertEqual(2, result["entry_count"])
        self.assertIn("-- SQL No.1", result["source_sql"])
        self.assertEqual("-- SQL No.1\nSELECT * FROM customers;", result["formatted_sql"])

    def test_database_settings_are_mapped_from_json(self) -> None:
        settings = _db_settings(
            {
                "database_type": "PostgreSQL",
                "host": "localhost",
                "port": "5432",
                "database": "sample",
                "schema": "public",
                "username": "tester",
                "password": "secret",
            }
        )

        self.assertIsInstance(settings, DatabaseConnectionSettings)
        self.assertEqual("PostgreSQL", settings.database_type)
        self.assertEqual("sample", settings.database)
        self.assertFalse(settings.trusted_connection)

    def test_database_connection_history_hides_password_and_reuses_session_password(self) -> None:
        app = AutoCompareWebApplication()
        settings = DatabaseConnectionSettings(
            database_type="SQL Server",
            host="db-host",
            port="1433",
            database="source_db",
            schema="dbo",
            username="tester",
            password="secret",
            trusted_connection=False,
            driver="ODBC Driver 18 for SQL Server",
        )

        app._remember_db_connection("main", settings)
        public_history = app._public_database_connection_history()
        restored = app._db_settings_for_role(
            {
                "database_type": "SQL Server",
                "host": "db-host",
                "port": "1433",
                "database": "target_db",
                "schema": "dbo",
                "username": "tester",
                "password": "",
                "trusted_connection": False,
                "driver": "ODBC Driver 18 for SQL Server",
                "trust_server_certificate": True,
                "encrypt": True,
            },
            "target",
        )

        self.assertEqual(1, len(public_history))
        self.assertEqual("source_db", public_history[0]["database"])
        self.assertEqual("", public_history[0]["password"])
        self.assertEqual("secret", restored.password)
        self.assertEqual("target_db", restored.database)

    def test_database_import_passes_existing_row_mode_to_workflow(self) -> None:
        app = AutoCompareWebApplication()
        payload = {
            "csv_path": str(Path.cwd()),
            "settings": {
                "database_type": "SQL Server",
                "host": ".",
                "database": "sample",
                "schema": "dbo",
                "trusted_connection": True,
            },
            "keep_identity": True,
            "existing_row_mode": "delete_matching_keys",
            "table_names": ["customers", "orders"],
        }
        summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=Path.cwd())
        cancel = type("Cancel", (), {"throw_if_cancelled": lambda self: None})()

        with patch("autocompare_tool.web_app.import_csv_folder", return_value=summary) as import_mock:
            operation = app._operation("db_import", payload)
            operation(lambda _message: None, cancel)

        self.assertTrue(import_mock.call_args.kwargs["keep_identity"])
        self.assertEqual("delete_matching_keys", import_mock.call_args.kwargs["existing_row_mode"])
        self.assertEqual(["customers", "orders"], import_mock.call_args.kwargs["table_names"])
        self.assertIsNotNone(import_mock.call_args.kwargs["log"])

    def test_database_sync_passes_incremental_options_to_workflow(self) -> None:
        app = AutoCompareWebApplication()
        connection = {
            "database_type": "SQL Server",
            "host": ".",
            "database": "sample",
            "schema": "dbo",
            "trusted_connection": True,
        }
        payload = {
            "source_settings": connection,
            "target_settings": connection,
            "table_names": ["customers"],
            "keep_identity": True,
            "sync_mode": "incremental",
            "batch_size": "5000",
            "delete_target_only": True,
        }

        with patch(
            "autocompare_tool.web_app.sync_database_tables",
            return_value=DatabaseSyncSummary(),
        ) as sync_mock:
            app._database_sync(payload, lambda _message: None)

        self.assertEqual("incremental", sync_mock.call_args.kwargs["sync_mode"])
        self.assertEqual("5000", sync_mock.call_args.kwargs["batch_size"])
        self.assertTrue(sync_mock.call_args.kwargs["delete_target_only"])
        self.assertTrue(sync_mock.call_args.kwargs["keep_identity"])


class JobManagerTests(unittest.TestCase):
    def test_job_collects_logs_and_result(self) -> None:
        manager = JobManager()

        manager.start("sample", "Đang chạy...", lambda log: self._successful_operation(log))
        snapshot = self._wait_until_finished(manager)

        self.assertEqual("succeeded", snapshot["state"])
        self.assertEqual(["Bước 1", "Bước 2"], snapshot["logs"])
        self.assertEqual({"value": 42}, snapshot["result"])

    def test_job_captures_operation_error(self) -> None:
        manager = JobManager()

        manager.start("sample", "Đang chạy...", self._failed_operation)
        snapshot = self._wait_until_finished(manager)

        self.assertEqual("failed", snapshot["state"])
        self.assertEqual("test failure", snapshot["error"])
        self.assertIn("LỖI: test failure", snapshot["logs"])

    @staticmethod
    def _successful_operation(log):
        log("Bước 1")
        log("Bước 2")
        return {"value": 42}

    @staticmethod
    def _failed_operation(_log):
        raise ValueError("test failure")

    def _wait_until_finished(self, manager: JobManager) -> dict:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snapshot = manager.snapshot()
            if snapshot is not None and snapshot["state"] in {"succeeded", "failed"}:
                return snapshot
            time.sleep(0.01)
        self.fail("Background job did not finish")


if __name__ == "__main__":
    unittest.main()
