from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from autocompare_tool.database_io import (
    CsvDbResult,
    DatabaseConnectionSettings,
    DatabaseCsvIssue,
    DatabaseCsvSuccess,
    DatabaseCsvSummary,
    DatabaseSyncSummary,
    MultiDatabaseCsvSummary,
)
from autocompare_tool.excel_format_presets import ExcelFormatPresetStore
from autocompare_tool.excel_image_formatter import ExcelImageFormatSummary
from autocompare_tool.excel_compare import ExcelCompareResult
from autocompare_tool.pdf_compare import PdfCompareResult
from autocompare_tool.excel_writer import WorkbookFixmeEntry
from autocompare_tool.sql_excel_loader import ExcelSqlEntry
from autocompare_tool.sql_tools import SqlFormatResult
from autocompare_tool.web_app import (
    AutoCompareServer,
    AutoCompareWebApplication,
    CancelToken,
    JobManager,
    _db_settings,
    _fixme_to_dict,
)


class WebApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Never read or overwrite the user's saved credentials during tests.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        history = patch("autocompare_tool.web_app.DB_CONNECTION_HISTORY_FILE", str(Path(directory.name) / "history.json"))
        history.start()
        self.addCleanup(history.stop)

    def test_retired_copy_ut_action_is_rejected_without_starting_a_job(self) -> None:
        app = AutoCompareWebApplication()
        with patch.object(app.jobs, "start") as start:
            with self.assertRaisesRegex(ValueError, "copy_ut"):
                app.start_action("copy_ut", {"source": "unused", "target": "unused", "confirmed": True})
            start.assert_not_called()

    def test_scan_compare_cases_lists_cases_under_the_chosen_root(self) -> None:
        app = AutoCompareWebApplication()
        folders = app.config.folders
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory) / f"{folders.case_pattern.rstrip('*')}01"
            (case / folders.output_dir / folders.after_htm_dir).mkdir(parents=True)
            result = app.scan_compare_cases({"root": directory})
            self.assertEqual([item["name"] for item in result["cases"]], [case.name])
            self.assertEqual(result["total"], 1)
            self.assertTrue(result["cases"][0]["has_output"])
            self.assertTrue(all(not flow["ready"] for flow in result["cases"][0]["workflows"][:1]))
            with self.assertRaises(NotADirectoryError):
                app.scan_compare_cases({"root": str(Path(directory) / "missing")})

    def test_open_result_only_serves_files_produced_by_this_session(self) -> None:
        app = AutoCompareWebApplication()
        with tempfile.TemporaryDirectory() as directory:
            produced = Path(directory) / "report.pdf"
            other = Path(directory) / "secret.txt"
            produced.write_bytes(b"%PDF")
            other.write_text("x")
            summary = type("Summary", (), {"output_path": produced})()
            app._remember_results(summary, "output_path")

            with self.assertRaises(PermissionError):
                app.open_result_path({"path": str(other)})
            with patch("autocompare_tool.web_app.os.startfile", create=True) as startfile:
                result = app.open_result_path({"path": str(produced)})
            startfile.assert_called_once_with(str(produced.resolve()))
            self.assertEqual(str(produced.resolve()), result["path"])

    def test_bootstrap_contains_web_defaults_and_workflows(self) -> None:
        app = AutoCompareWebApplication()

        result = app.bootstrap(9876)

        self.assertEqual(9876, result["port"])
        self.assertEqual(str(Path.cwd()), result["cwd"])
        self.assertTrue(result["build_marker"])
        self.assertTrue(result["compare_workflows"])
        self.assertIn("SQL Server", result["database_types"])
        self.assertIn("folder_compare_file", result)
        self.assertIn("excel_format_presets", result)
        self.assertEqual(result["compare_options"], {"copy_input": False, "sort_by_key": False})
        self.assertIs(result["multi_database_default"], False)

    def test_bootstrap_reads_multi_database_default_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "autocompare_config.ini"
            config_path.write_text("[database]\nmulti_database_default = true\n", encoding="utf-8")
            with patch("autocompare_tool.app_config.default_config_path", return_value=config_path):
                result = AutoCompareWebApplication().bootstrap(9876)
        self.assertIs(result["multi_database_default"], True)

    def test_web_server_rejects_second_bind_on_same_port(self) -> None:
        first = AutoCompareServer(("127.0.0.1", 0), object())
        try:
            with self.assertRaises(OSError):
                second = AutoCompareServer(("127.0.0.1", first.server_address[1]), object())
                second.server_close()
        finally:
            first.server_close()

    def test_compare_forwards_explicit_file_options(self) -> None:
        from autocompare_tool.processor import ProcessSummary

        app = AutoCompareWebApplication()
        for options in ({}, {"copy_input": True, "sort_by_key": True, "sheet_zoom": 75},
                        {"copy_input": "false", "sort_by_key": "true"}):
            with self.subTest(options=options), patch(
                "autocompare_tool.web_app.process_root", return_value=ProcessSummary(Path.cwd()),
            ) as process:
                app._compare({"root": str(Path.cwd()), "workflows": ["htm_before_after"], **options}, lambda _: None)
                self.assertEqual(process.call_args.kwargs["copy_input"], options.get("copy_input") is True)
                self.assertEqual(process.call_args.kwargs["sort_by_key"], options.get("sort_by_key") is True)
                self.assertEqual(process.call_args.kwargs["sheet_zoom"], options.get("sheet_zoom", 85))

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
            app.start_action("format_excel_workbooks", {"root": str(Path.cwd())})

        with self.assertRaises(ValueError):
            app.start_action("format_excel_images", {"root": str(Path.cwd()), "confirmed": True})

    def test_excel_format_action_maps_safe_copy_options(self) -> None:
        app = AutoCompareWebApplication()
        summary = ExcelImageFormatSummary(
            action_name="Format workbook Excel",
            root_path=Path.cwd(),
            output_root=Path.cwd() / "Formatted",
        )
        payload = {
            "root": str(Path.cwd()),
            "recursive": False,
            "overwrite_original": False,
            "run_image_format": True,
            "font_name": "Calibri",
            "font_size": "12",
            "font_size_exclusions": "Header\n(Title, A1)",
            "apply_font_name": False,
            "apply_font_size": True,
            "apply_exclusions": False,
            "select_a1": False,
            "reset_scroll": True,
            "activate_first_sheet": False,
        }

        with patch("autocompare_tool.web_app.format_excel_workbooks", return_value=summary) as format_mock:
            result = app._operation("format_excel_workbooks", payload)(lambda _message: None, CancelToken())

        self.assertEqual(0, result["processed_count"])
        self.assertEqual(str(Path.cwd() / "Formatted"), result["output_root"])
        self.assertFalse(format_mock.call_args.kwargs["recursive"])
        self.assertFalse(format_mock.call_args.kwargs["overwrite_original"])
        self.assertNotIn("draw_format", format_mock.call_args.kwargs)
        self.assertNotIn("run_image_format", format_mock.call_args.kwargs)
        self.assertEqual("Calibri", format_mock.call_args.kwargs["font_name"])
        self.assertEqual("12", format_mock.call_args.kwargs["font_size"])
        self.assertEqual("", format_mock.call_args.kwargs["font_size_exclusions"])
        self.assertFalse(format_mock.call_args.kwargs["apply_font_name"])
        self.assertTrue(format_mock.call_args.kwargs["apply_font_size"])
        self.assertFalse(format_mock.call_args.kwargs["select_a1"])
        self.assertTrue(format_mock.call_args.kwargs["reset_scroll"])
        self.assertFalse(format_mock.call_args.kwargs["activate_first_sheet"])

    def test_excel_compare_action_maps_paths_and_returns_json_safe_result(self) -> None:
        app = AutoCompareWebApplication()
        old_path = Path.cwd() / "old.xlsx"
        new_path = Path.cwd() / "new.xlsx"
        output_path = Path.cwd() / "Compare_Excel.xlsx"
        summary = ExcelCompareResult(old_path, new_path, "test-report", 2, 5, 0, 0, False, False, ())

        with patch("autocompare_tool.web_app.compare_excel_workbooks", return_value=summary) as compare_mock:
            operation = app._operation("excel_compare", {
                "old_path": str(old_path),
                "new_path": str(new_path),
                "output_path": str(output_path),
            })
            result = operation(lambda _message: None, CancelToken())

        self.assertEqual("test-report", result["report_id"])
        self.assertNotIn("output_path", result)
        self.assertEqual(str(old_path), result["old_path"])
        self.assertEqual(5, result["difference_count"])
        self.assertEqual((str(old_path), str(new_path)), compare_mock.call_args.args)
        self.assertIs(app.excel_compare_store, compare_mock.call_args.kwargs["store"])
        self.assertEqual(app.config.excel_compare.max_detail_rows, compare_mock.call_args.kwargs["max_detail_rows"])
        self.assertEqual(set(), app._openable_results)

    def test_excel_differences_endpoint_returns_filtered_pages_and_truncation(self) -> None:
        app = AutoCompareWebApplication()
        # Use a small in-memory config override to exercise truncation with small workbooks.
        app.config = replace(app.config, excel_compare=replace(app.config.excel_compare, max_detail_rows=2))
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name, row in (("old", ["Header", 1, 2, 3]), ("new", ["Header", 4, 5, 6])):
            book = Workbook()
            book.active.append(row)
            book.save(directory / f"{name}.xlsx")
        operation = app._operation("excel_compare", {
            "old_path": str(directory / "old.xlsx"),
            "new_path": str(directory / "new.xlsx"),
        })
        summary = operation(lambda _message: None, CancelToken())
        self.addCleanup(app.excel_compare_store.delete, summary["report_id"])
        self.assertEqual(3, summary["difference_count"])
        self.assertTrue(summary["details_truncated"])
        self.assertNotIn("output_path", summary)
        self.assertEqual(0, summary["sheets"][0]["index"])

        address = self._start_test_server(app)
        payload = {"report_id": summary["report_id"], "sheet": 0, "limit": 1}
        status, page = _post_excel_differences(address, payload)
        self.assertEqual(200, status)
        self.assertEqual({
            "total": 2,
            "rows": [{"row": 1, "col": 2, "coord": "B1", "column": "B", "change_type": "changed",
                      "header": "4", "old": "1", "new": "4"}],
            "truncated": True,
        }, page)
        self.assertEqual("C1", _post_excel_differences(address, dict(payload, offset=1))[1]["rows"][0]["coord"])
        _, filtered = _post_excel_differences(address, dict(payload, column="C", search="5", change_types=["changed"]))
        self.assertEqual((1, ["C1"]), (filtered["total"], [row["coord"] for row in filtered["rows"]]))
        self.assertEqual(400, _post_excel_differences(address, dict(payload, column="XFE"))[0])
        self.assertEqual(400, _post_excel_differences(address, dict(payload, sheet=-1))[0])
        app.excel_compare_store.delete(summary["report_id"])
        status, expired = _post_excel_differences(address, payload)
        self.assertEqual(404, status)
        self.assertIn("hết hạn", expired["error"])

    def test_excel_differences_endpoint_rejects_unknown_reports_and_invalid_types(self) -> None:
        address = self._start_test_server(AutoCompareWebApplication())
        payload = {"report_id": "missing", "sheet": 0}
        status, result = _post_excel_differences(address, payload)
        self.assertEqual(404, status)
        self.assertIn("không tồn tại", result["error"])
        for key, value in (
            ("report_id", 12), ("sheet", True), ("offset", 1.5), ("limit", "50"),
            ("search", None), ("column", 2), ("change_types", "changed"),
            ("change_types", ["unknown"]), ("change_types", [{}]),
        ):
            with self.subTest(key=key, value=value):
                status, result = _post_excel_differences(address, dict(payload, **{key: value}))
                self.assertEqual(400, status)
                self.assertIn(key, result["error"])

    def _start_test_server(self, app: AutoCompareWebApplication) -> tuple[str, int]:
        server = self.enterContext(AutoCompareServer(("127.0.0.1", 0), app))
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(server.shutdown)
        return server.server_address

    def test_pdf_compare_action_maps_paths_and_returns_json_safe_result(self) -> None:
        app = AutoCompareWebApplication()
        old_path = Path.cwd() / "old.pdf"
        new_path = Path.cwd() / "new.pdf"
        output_path = Path.cwd() / "Compare_PDF.pdf"
        manifest_path = output_path.with_suffix(".json")
        summary = PdfCompareResult(
            old_path, new_path, output_path, manifest_path,
            "DIFFERENT", False, False, False, False, True,
            "a" * 64, "b" * 64, 2, 2, 2, 1, 3,
        )

        with patch("autocompare_tool.web_app.compare_pdf_files", return_value=summary) as compare_mock:
            operation = app._operation("pdf_compare", {
                "old_path": str(old_path),
                "new_path": str(new_path),
                "output_path": str(output_path),
            })
            from autocompare_tool.web_app import CancelToken
            result = operation(lambda _message: None, CancelToken())

        self.assertEqual(str(output_path), result["output_path"])
        self.assertEqual(str(manifest_path), result["manifest_path"])
        self.assertEqual("DIFFERENT", result["verdict"])
        self.assertEqual(str(old_path), compare_mock.call_args.args[0])
        self.assertEqual(str(new_path), compare_mock.call_args.args[1])

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
            )(lambda _message: None, CancelToken())

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
                )(lambda _message: None, CancelToken())

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
        self.assertFalse(settings.encrypt)

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
                "encrypt": False,
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

        for trigger_option, expected in (({}, False), ({"disable_triggers": True}, True), ({"disable_triggers": "false"}, False)):
            with self.subTest(trigger_option=trigger_option):
                with patch("autocompare_tool.web_app.import_csv_folder", return_value=summary) as import_mock:
                    operation = app._operation("db_import", {**payload, **trigger_option})
                    operation(lambda _message: None, cancel)

                self.assertTrue(import_mock.call_args.kwargs["keep_identity"])
                self.assertIs(import_mock.call_args.kwargs["disable_triggers"], expected)
                self.assertEqual("delete_matching_keys", import_mock.call_args.kwargs["existing_row_mode"])
                self.assertEqual(["customers", "orders"], import_mock.call_args.kwargs["table_names"])
                self.assertIsNotNone(import_mock.call_args.kwargs["log"])

    def test_database_summary_keeps_legacy_keys_and_serializes_table_results(self) -> None:
        root = Path.cwd()
        summary = DatabaseCsvSummary(
            action_name="Nhập CSV vào CSDL",
            root_path=root,
            csv_results=[CsvDbResult(root / "customers.csv", "customers", 3)],
            errors=["LỖI orders.csv: bad key"],
            skipped=["empty.csv -> bỏ qua CSV rỗng"],
            succeeded=[DatabaseCsvSuccess("customers", 3)],
            failed=[DatabaseCsvIssue("orders", "bad key")],
            skipped_items=[DatabaseCsvIssue("empty", "bỏ qua CSV rỗng")],
        )

        self.assertEqual(AutoCompareWebApplication._database_summary(summary), {
            "action_name": "Nhập CSV vào CSDL",
            "root_path": str(root),
            "csv_count": 1,
            "row_count": 3,
            "error_count": 1,
            "errors": ["LỖI orders.csv: bad key"],
            "skipped": ["empty.csv -> bỏ qua CSV rỗng"],
            "succeeded": [{"table": "customers", "rows": 3}],
            "failed": [{"table": "orders", "message": "bad key"}],
            "skipped_items": [{"table": "empty", "message": "bỏ qua CSV rỗng"}],
        })

    def test_import_and_export_use_the_single_settings_path_without_connections(self) -> None:
        app = AutoCompareWebApplication()
        root = Path.cwd()
        summary = DatabaseCsvSummary("CSV", root, succeeded=[DatabaseCsvSuccess("items", 1)])
        settings = {"host": ".", "database": "sample", "trusted_connection": True}
        for action, workflow in (("db_import", "import_csv_folder"), ("db_export", "export_csv_folder")):
            for connections in ({}, {"connections": []}):
                with self.subTest(action=action, connections=connections), patch(
                    f"autocompare_tool.web_app.{workflow}", return_value=summary,
                ) as single:
                    payload = {"csv_path": str(root), "settings": settings, **connections}
                    result = app._operation(action, payload)(lambda _: None, CancelToken())

                self.assertEqual(single.call_args.args[1], _db_settings(settings))
                self.assertEqual(list(result), [
                    "action_name", "root_path", "csv_count", "row_count", "error_count", "errors",
                    "skipped", "succeeded", "failed", "skipped_items",
                ])
                self.assertEqual(result["succeeded"], [{"table": "items", "rows": 1}])

    def test_multi_database_payload_validation(self) -> None:
        app = AutoCompareWebApplication()
        settings = {"host": ".", "database": "sample", "trusted_connection": True}
        main = {"id": "main", "settings": settings}
        extras = [
            {"id": f"extra-{index}", "settings": {**settings, "database": f"db{index}"}}
            for index in range(1, 10)
        ]
        duplicate = {"id": "target", "settings": settings}
        target = {"id": "target", "settings": {**settings, "database": "target"}}
        for connections, message in (
            ({}, "danh sách"), (None, "danh sách"),
            ([None], "settings"), ([{"id": "main"}], "settings"),
            ([{"id": "main", "settings": {}}], "settings"),
            ([{**main, "id": "extra-123"}], "extra-123"),
            ([{**main, "id": ""}], "không hợp lệ"),
            ([main, {**main, "settings": {**settings, "database": "other"}}], "Trùng id"),
            ([main, duplicate], "Trùng thông tin"),
            ([main, {**duplicate, "settings": {**settings, "database_type": "mssql", "schema": "dbo"}}], "Trùng thông tin"),
            ([main, target, *extras], "tối đa 10"), (extras, "tối đa 8"),
        ):
            with self.subTest(connections=connections), self.assertRaisesRegex(ValueError, message):
                app.start_action("db_import", {"connections": connections, "confirmed": True})
        self.assertEqual(len(app._multi_db_connections({"connections": [main, target, *extras[:8]]})), 10)
        with self.assertRaises(PermissionError):
            app.start_action("db_import", {"connections": [main]})

    def test_multi_database_actions_recover_passwords_and_serialize_database_details(self) -> None:
        app = AutoCompareWebApplication()
        settings = {"host": ".", "database": "sample", "username": "tester"}
        app._remember_db_connection("extra-12", _db_settings({**settings, "password": "stored"}))
        root = Path.cwd()
        label = "sample @ ."
        summary = MultiDatabaseCsvSummary("CSV", root, [
            (label, DatabaseCsvSummary("CSV", root,
                csv_results=[CsvDbResult(root / "items.csv", "items", 1)],
                succeeded=[DatabaseCsvSuccess("items", 1)],
            )),
            (f"{label} (2)", DatabaseCsvSummary("CSV", root, errors=["connection refused"],
                failed=[DatabaseCsvIssue("<kết nối>", "connection refused")],
                skipped_items=[DatabaseCsvIssue("duplicate", "trùng tên")],
            )),
        ], [DatabaseCsvIssue("missing", "Không tìm thấy table trong database đã chọn")])
        payload = {
            "csv_path": str(root),
            "connections": [
                {"id": "extra-12", "settings": settings},
                {"id": "main", "settings": {**settings, "schema": "other"}},
            ],
            "table_names": ["items"], "keep_identity": True, "disable_triggers": True,
            "existing_row_mode": "truncate_table",
        }
        for action, workflow in (("db_import", "import_csv_folder_multi"), ("db_export", "export_csv_folder_multi")):
            with self.subTest(action=action), patch(
                f"autocompare_tool.web_app.{workflow}", return_value=summary,
            ) as multi:
                token = CancelToken()
                result = app._operation(action, payload)(lambda _: None, token)

                self.assertEqual(multi.call_args.args[1], [
                    (label, _db_settings({**settings, "password": "stored"})),
                    (f"{label} (2)", _db_settings({**settings, "schema": "other", "password": "stored"})),
                ])
                self.assertEqual(multi.call_args.kwargs["cancel"], token.throw_if_cancelled)
                if action == "db_import":
                    self.assertTrue(multi.call_args.kwargs["keep_identity"])
                    self.assertTrue(multi.call_args.kwargs["disable_triggers"])
                    self.assertEqual(multi.call_args.kwargs["existing_row_mode"], "truncate_table")
                    self.assertEqual(multi.call_args.kwargs["table_names"], ["items"])
                else:
                    self.assertEqual(multi.call_args.args[2], ["items"])

                self.assertEqual(result["databases"], [
                    {"label": label, "csv_count": 1, "row_count": 1, "error_count": 0, "skipped_count": 0},
                    {"label": f"{label} (2)", "csv_count": 0, "row_count": 0, "error_count": 1, "skipped_count": 1},
                ])
                self.assertEqual(result["succeeded"], [{"table": f"{label}: items", "rows": 1, "database": label}])
                self.assertEqual(result["failed"], [{
                    "table": f"{label} (2): <kết nối>", "message": "connection refused", "database": f"{label} (2)",
                }])
                self.assertEqual(result["skipped_items"], [
                    {"table": f"{label} (2): duplicate", "message": "trùng tên", "database": f"{label} (2)"},
                    {"table": "missing", "message": "Không tìm thấy table trong database đã chọn"},
                ])

    def test_extra_roles_can_test_list_and_extract_and_survive_session_swap(self) -> None:
        app = AutoCompareWebApplication()
        role = "extra-12"
        settings = {"host": ".", "database": "extra", "username": "tester", "password": "stored"}
        with patch("autocompare_tool.web_app.test_database_connection"), patch(
            "autocompare_tool.web_app.list_database_tables", return_value=[],
        ), patch("autocompare_tool.web_app.list_database_names", return_value=["extra"]) as list_names:
            tested = app._db_test({"role": role, "settings": settings, "load_tables": True}, lambda _: None)
            public = tested["connection"]
            self.assertEqual((tested["role"], public["password"]), (role, ""))
            listed = app._db_list_databases({"role": role, "settings": public}, lambda _: None)
            self.assertEqual((listed["role"], listed["databases"]), (role, ["extra"]))
            self.assertEqual(app._db_list_tables({"role": role, "settings": public}, lambda _: None)["tables"], [])
            list_names.assert_called_once_with(_db_settings(settings))

        app._remember_db_connection("main", _db_settings({**settings, "database": "main"}), ["a"])
        app._remember_db_connection("target", _db_settings({**settings, "database": "target"}), ["b"])
        result = app.switch_database_session_cache()
        self.assertEqual(result["database_connections"]["main"]["database"], "target")
        self.assertEqual(result["database_connections"]["target"]["database"], "main")
        self.assertEqual(result["database_tables"], {"main": ["b"], "target": ["a"], role: []})
        self.assertEqual(app.bootstrap(9876)["database_connections"][role], public)
        app._operation("compare_keys_extract", {"role": role})

        for operation in (app._db_test, app._db_list_databases, app._db_list_tables):
            with self.assertRaisesRegex(ValueError, "extra-100"):
                operation({"role": "extra-100", "settings": public}, lambda _: None)

    def test_connection_cache_limits_distinct_extra_roles(self) -> None:
        app = AutoCompareWebApplication()
        settings = _db_settings({"host": ".", "database": "sample", "trusted_connection": True})
        for index in range(8):
            app._remember_db_connection(f"extra-{index}", settings, [])
        app._remember_db_connection("extra-0", settings, ["updated"])
        with self.assertRaisesRegex(ValueError, "tối đa 8"):
            app._remember_db_connection("extra-75", settings)
        self.assertEqual(len(app._public_database_connection_cache()), 8)
        self.assertEqual(app._public_database_table_cache()["extra-0"], ["updated"])

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
            "autocompare_tool.web_app.run_sync_isolated",
            return_value=DatabaseSyncSummary(),
        ) as sync_mock:
            app._database_sync(payload, lambda _message: None)

        self.assertEqual("incremental", sync_mock.call_args.kwargs["sync_mode"])
        self.assertEqual("5000", sync_mock.call_args.kwargs["batch_size"])
        self.assertEqual(120, sync_mock.call_args.kwargs["step_timeout"])
        self.assertTrue(sync_mock.call_args.kwargs["delete_target_only"])
        self.assertTrue(sync_mock.call_args.kwargs["keep_identity"])


def _post_excel_differences(address: tuple[str, int], payload: dict) -> tuple[int, dict]:
    client = HTTPConnection(*address, timeout=5)
    try:
        client.request("POST", "/api/excel-compare/differences", json.dumps(payload),
                       {"Content-Type": "application/json"})
        response = client.getresponse()
        return response.status, json.loads(response.read())
    finally:
        client.close()


class JobManagerTests(unittest.TestCase):
    def test_job_collects_logs_and_result(self) -> None:
        manager = JobManager()

        manager.start("sample", "Đang chạy...", lambda log, cancel: self._successful_operation(log))
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
    def _failed_operation(_log, _cancel):
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
