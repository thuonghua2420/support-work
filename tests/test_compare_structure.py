import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from autocompare_tool.app_config import load_app_config
from autocompare_tool.compare_structure import read_compare_structure, save_compare_structure
from autocompare_tool.dbeaver_csv import write_dbeaver_csv
from autocompare_tool.processor import process_root


class CompareStructureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.path = self.root / "config.ini"
        self.original = (
            "# User comment\r\n[folders]\r\ninput_dir = 入力データ\r\n"
            "output_dir = Output\r\ncompare_dir = Compare\r\n"
            "before_htm_dir = before_htm\r\nafter_htm_dir = after_htm\r\n"
            "before_htc_dir = before_htc\r\nafter_htc_dir = after_htc\r\n"
            "[workbooks]\r\nhtm_before_after_file = htm.xlsx\r\n"
            "htc_before_after_file = htc.xlsx\r\nafter_htc_vs_htm_file = after.xlsx\r\n"
            "folder_compare_file = folders.xlsx\r\n"
            "# Keep this key exactly\r\n[update_compare_keys]\r\nORDERS = Tenant, Id\r\n"
            "[excel_headers_htm_before_after]\r\nleft_column_title = 旧列名\r\n"
            "[custom]\r\nuntouched = 100%\r\n"
        ).encode("utf-8")
        self.path.write_bytes(self.original)

    def test_save_preserves_comments_unrelated_settings_and_line_endings(self):
        draft = read_compare_structure(self.path)
        draft["folders"]["input_dir"] = "入力・更新"
        draft["folders"]["output_dir"] = "Output_更新"
        draft["workbooks"]["htm_before_after_file"] = "比較_HTM.xlsx"
        result = save_compare_structure(draft, self.path)
        raw = self.path.read_bytes()
        expected = self.original.replace("input_dir = 入力データ".encode(), "input_dir = 入力・更新".encode())
        expected = expected.replace(b"output_dir = Output", "output_dir = Output_更新".encode())
        expected = expected.replace(b"htm_before_after_file = htm.xlsx", "htm_before_after_file = 比較_HTM.xlsx".encode())
        self.assertEqual(raw, expected)
        self.assertNotEqual(result["revision"], draft["revision"])
        self.assertEqual(result["workbooks"]["htm_before_after_file"], "比較_HTM.xlsx")
        config = load_app_config(self.path)
        self.assertEqual(config.compare_workflows[0].output_file_name, "比較_HTM.xlsx")
        self.assertEqual(config.update_compare_keys, {"orders": ("Tenant", "Id")})
        self.assertEqual(config.workbooks.folder_compare_file, "folders.xlsx")

    def test_invalid_names_and_collisions_do_not_write_anything(self):
        cases = [("folders", "input_dir", value) for value in (
            "", "../other", "..", r"C:\data", "a/b", "a\\b", "a:b", "a?b", "bad\nname", "a.", "NUL.csv", "COM1", "output", "a" * 256,
        )]
        cases.extend([("folders", "compare_dir", "BEFORE_HTM"),
                      ("workbooks", "htm_before_after_file", "HTC.xlsx"),
                      ("workbooks", "htm_before_after_file", "report.csv")])
        for section, key, value in cases:
            with self.subTest(section=section, key=key, value=value):
                draft = read_compare_structure(self.path)
                draft[section][key] = value
                with self.assertRaises(ValueError):
                    save_compare_structure(draft, self.path)
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_stale_revision_requires_reload(self):
        draft = read_compare_structure(self.path)
        latest = self.original + b"# Changed externally\r\n"
        self.path.write_bytes(latest)
        with self.assertRaises(RuntimeError):
            save_compare_structure(draft, self.path)
        self.assertEqual(self.path.read_bytes(), latest)

    def test_missing_or_extra_fields_are_rejected(self):
        original = read_compare_structure(self.path)
        for operation in (lambda data: data["folders"].pop("input_dir"),
                          lambda data: data["workbooks"].update(folder_compare_file="extra.xlsx")):
            draft = copy.deepcopy(original)
            operation(draft)
            with self.assertRaises(ValueError):
                save_compare_structure(draft, self.path)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_empty_config_and_bom_can_be_saved(self):
        for raw in (b"", b"\xef\xbb\xbf" + self.original):
            with self.subTest(bom=bool(raw)):
                self.path.write_bytes(raw)
                draft = read_compare_structure(self.path)
                saved = save_compare_structure(draft, self.path)
                self.assertEqual(saved["folders"], draft["folders"])
                self.assertEqual(self.path.read_bytes().startswith(b"\xef\xbb\xbf"), bool(raw))

    def test_replace_failure_leaves_config_intact_and_cleans_temp_file(self):
        draft = read_compare_structure(self.path)
        draft["folders"]["input_dir"] = "Input"
        with patch("autocompare_tool.compare_structure.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                save_compare_structure(draft, self.path)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob(".compare-config-*")))

    def test_next_compare_reads_the_saved_tree_without_touching_csv(self):
        draft = read_compare_structure(self.path)
        draft["folders"]["output_dir"] = "Updated Output"
        draft["folders"]["compare_dir"] = "Results"
        draft["folders"]["before_htm_dir"] = "Before New"
        draft["folders"]["after_htm_dir"] = "After New"
        draft["workbooks"]["htm_before_after_file"] = "Updated Compare.xlsx"
        save_compare_structure(draft, self.path)
        config = load_app_config(self.path)
        case = self.root / "UT01"
        for folder, value in (("Before New", "old"), ("After New", "new")):
            write_dbeaver_csv(case / "Updated Output" / folder / "orders.csv", ["id", "name"], [["1", value]])
        original = {path: path.read_bytes() for path in case.rglob("*.csv")}
        result = process_root(case, config=config, selected_workflow_keys={"htm_before_after"})
        self.assertFalse(result.errors)
        output = case / "Updated Output" / "Results" / "Updated Compare.xlsx"
        self.assertEqual(result.test_cases[0].workbooks[0].output_path, output)
        with output.open("rb") as stream:
            workbook = load_workbook(stream)
            self.assertEqual(workbook.active.title, "orders")
            workbook.close()
        self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_web_save_refreshes_config_and_rejects_running_jobs(self):
        from autocompare_tool.web_app import AutoCompareWebApplication

        with patch("autocompare_tool.app_config.default_config_path", return_value=self.path), \
             patch("autocompare_tool.compare_structure.default_config_path", return_value=self.path), \
             patch("autocompare_tool.web_app.DB_CONNECTION_HISTORY_FILE", str(self.root / "history.json")):
            app = AutoCompareWebApplication()
            self.addCleanup(app.sql_workspace.close)
            draft = read_compare_structure(self.path)
            draft["folders"]["compare_dir"] = "New Results"
            with patch.object(app.jobs, "snapshot", return_value={"state": "running"}):
                with self.assertRaises(RuntimeError):
                    app.save_compare_structure(draft)
            self.assertEqual(self.path.read_bytes(), self.original)
            app.save_compare_structure(draft)
            self.assertEqual(app.config.folders.compare_dir, "New Results")
            self.assertEqual(app.config.compare_workflows[0].left_dir_name, draft["folders"]["before_htm_dir"])


if __name__ == "__main__":
    unittest.main()
