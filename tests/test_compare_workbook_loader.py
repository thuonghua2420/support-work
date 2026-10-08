from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from openpyxl import Workbook, load_workbook

    from autocompare_tool.app_config import load_app_config
    from autocompare_tool.excel_writer import write_compare_workbook_with_fixmes
    from autocompare_tool.web_app import AutoCompareWebApplication
except ImportError:  # pragma: no cover - optional dependency guard for minimal environments.
    Workbook = None
    load_workbook = None
    load_app_config = None
    write_compare_workbook_with_fixmes = None
    AutoCompareWebApplication = None


@unittest.skipIf(load_workbook is None, "openpyxl is not installed")
class CompareWorkbookLoaderTests(unittest.TestCase):
    def test_loads_multiple_cases_and_reopens_notes_for_editing(self) -> None:
        config = load_app_config()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outputs = []
            for case_name in ("UT01", "UT02"):
                case = root / case_name
                before = case / "before"
                after = case / "after"
                before.mkdir(parents=True)
                after.mkdir()
                (before / "table.csv").write_text("id,name\n1,old\n", encoding="utf-8")
                (after / "table.csv").write_text("id,name\n1,new\n", encoding="utf-8")
                output = case / config.folders.output_dir / config.folders.compare_dir / "saved.xlsx"
                write_compare_workbook_with_fixmes(
                    before, after, output, case_folder_name=case_name,
                    excel_headers=config.excel_headers, excel_style=config.excel_compare_style,
                )
                outputs.append(output)

            unrelated = outputs[0].parent / "unrelated.xlsx"
            workbook = Workbook()
            workbook.active["A1"] = "unrelated"
            workbook.save(unrelated)
            workbook.close()

            app = AutoCompareWebApplication()
            original_bytes = [output.read_bytes() for output in outputs]
            result = app._load_compare_workbooks({"root": str(root)}, lambda _message: None)
            self.assertEqual(original_bytes, [output.read_bytes() for output in outputs])
            self.assertEqual(2, result["case_count"])
            self.assertEqual(2, result["workbook_count"])
            self.assertEqual(2, result["fixme_count"])
            self.assertEqual(["UT01", "UT02"], [case["name"] for case in result["compare_view"]["cases"]])
            self.assertEqual(["saved.xlsx"], [book["name"] for book in result["compare_view"]["cases"][0]["workbooks"]])
            self.assertEqual(["table"], [sheet["name"] for sheet in result["compare_view"]["cases"][0]["workbooks"][0]["sheets"]])
            with self.assertRaisesRegex(ValueError, "không tồn tại"):
                app._load_compare_workbooks({"root": str(root / "missing")}, lambda _message: None)
            self.assertEqual(2, len(app.compare_view_index()["cases"]))

            first = result["fixmes"][0]
            self.assertEqual("name", first["column_name"])
            self.assertEqual("old", first["left_value"])
            self.assertEqual("new", first["right_value"])
            self.assertEqual([0], app.compare_sheet_snapshot("0", "table")["rows"][3]["cells"][-1]["fixme_indices"])

            app._apply_fixmes({"selections": {"0": "Note đầu"}}, lambda _message: None)
            saved = load_workbook(outputs[0])
            self.assertEqual("Note đầu", saved["table"][first["fixme_cell"]].value)
            saved.close()
            reloaded = app._load_compare_workbooks({"root": str(root / "UT01")}, lambda _message: None)
            self.assertEqual(1, reloaded["fixme_count"])
            app._apply_fixmes({"selections": {"0": "Note mới"}}, lambda _message: None)
            saved = load_workbook(outputs[0])
            self.assertEqual("Note mới", saved["table"][first["fixme_cell"]].value)
            saved.close()

    def test_empty_selection_keeps_current_workbooks(self) -> None:
        app = AutoCompareWebApplication()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "UT01").mkdir()
            with self.assertRaisesRegex(ValueError, "Không tìm thấy workbook Compare"):
                app._load_compare_workbooks({"root": str(root)}, lambda _message: None)
            self.assertEqual([], app.compare_view_index()["cases"])

    def test_older_compare_headers_are_recognized_by_layout(self) -> None:
        config = load_app_config()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "UT01"
            before = root / "before"
            after = root / "after"
            before.mkdir(parents=True)
            after.mkdir()
            (before / "table.csv").write_text("id,name\n1,old\n", encoding="utf-8")
            (after / "table.csv").write_text("id,name\n1,new\n", encoding="utf-8")
            output = root / config.folders.output_dir / config.folders.compare_dir / "saved.xlsx"
            write_compare_workbook_with_fixmes(before, after, output)
            workbook = load_workbook(output)
            sheet = workbook["table"]
            sheet["A1"] = "Old diff title"
            sheet["A2"] = "Old left title"
            sheet["B2"] = "Old right title"
            workbook.save(output)
            workbook.close()

            result = AutoCompareWebApplication()._load_compare_workbooks({"root": str(root)}, lambda _message: None)
            self.assertEqual(1, result["workbook_count"])
            self.assertEqual(1, result["fixme_count"])

    def test_reconstructs_mismatch_when_both_excel_values_look_blank(self) -> None:
        config = load_app_config()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "UT01"
            before = root / "before"
            after = root / "after"
            before.mkdir(parents=True)
            after.mkdir()
            (before / "table.csv").write_text("id,name\n1,\n", encoding="utf-8")
            (after / "table.csv").write_text("id,name\n", encoding="utf-8")
            output = root / config.folders.output_dir / config.folders.compare_dir / "saved.xlsx"
            write_result = write_compare_workbook_with_fixmes(before, after, output)

            result = AutoCompareWebApplication()._load_compare_workbooks({"root": str(root)}, lambda _message: None)
            self.assertEqual(len(write_result.fixme_entries), result["fixme_count"])
            self.assertIn("name", [entry["column_name"] for entry in result["fixmes"]])
