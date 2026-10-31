import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from autocompare_tool.app_config import load_app_config
from autocompare_tool.compare_structure import read_compare_structure, save_compare_structure
from autocompare_tool.dbeaver_csv import write_dbeaver_csv
from autocompare_tool.processor import describe_test_cases, discover_test_cases, process_root
from autocompare_tool.compare_workbook_loader import load_ut_compare_workbooks


class CompareStructureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.path = self.root / "config.ini"
        self.original = (
            "# User comment\r\n[folders]\r\ncase_pattern = UT*\r\ninput_dir = 入力データ\r\n"
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
        cases.extend(("folders", "case_pattern", value) for value in ("", "../Case*", "..", r"C:\Cases", "Case/??", "bad\npattern"))
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

    def test_old_config_defaults_to_ut_pattern_and_saves_new_option(self):
        self.path.write_bytes(self.original.replace(b"case_pattern = UT*\r\n", b""))
        self.assertEqual(load_app_config(self.path).folders.case_pattern, "UT*")
        draft = read_compare_structure(self.path)
        draft["folders"]["case_pattern"] = "Case*"
        save_compare_structure(draft, self.path)
        self.assertEqual(load_app_config(self.path).folders.case_pattern, "Case*")
        self.assertIn(b"case_pattern = Case*\r\n", self.path.read_bytes())

    def test_custom_pattern_is_shared_by_compare_and_loading_from_parent_or_case(self):
        draft = read_compare_structure(self.path)
        draft["folders"]["case_pattern"] = "Case*"
        save_compare_structure(draft, self.path)
        config = load_app_config(self.path)
        for case in ("Case01", "case02", "UT01"):
            for folder, value in (("before_htm", "old"), ("after_htm", "new")):
                write_dbeaver_csv(self.root / case / "Output" / folder / "orders.csv", ["id", "name"], [["1", value]])
        result = process_root(self.root, config=config, selected_workflow_keys={"htm_before_after"})
        self.assertFalse(result.errors)
        self.assertEqual([case.case_path.name for case in result.test_cases], ["Case01", "case02"])
        self.assertFalse((self.root / "UT01" / "Output" / "Compare").exists())
        references, _ = load_ut_compare_workbooks(self.root, config)
        self.assertEqual([ref.case_folder_name for ref in references], ["Case01", "case02"])
        case_root = self.root / "Case01"
        single = process_root(case_root, config=config, selected_workflow_keys={"htm_before_after"})
        self.assertFalse(single.errors)
        references, _ = load_ut_compare_workbooks(case_root, config)
        self.assertEqual([ref.case_folder_name for ref in references], ["Case01"])

    def test_describe_reports_each_case_and_which_workflows_have_their_folders(self):
        config = load_app_config(self.path)
        write_dbeaver_csv(self.root / "UT01" / "Output" / "before_htm" / "a.csv", ["id"], [["1"]])
        write_dbeaver_csv(self.root / "UT01" / "Output" / "after_htm" / "a.csv", ["id"], [["1"]])
        write_dbeaver_csv(self.root / "UT01" / "Output" / "after_htm" / "b.csv", ["id"], [["1"]])
        write_dbeaver_csv(self.root / "UT01" / "入力データ" / "a.csv", ["id"], [["1"]])
        (self.root / "UT02").mkdir()
        (self.root / "Other").mkdir()

        info = describe_test_cases(self.root, config)

        self.assertEqual(info["total"], 2)
        self.assertEqual([case["name"] for case in info["cases"]], ["UT01", "UT02"])
        first, second = info["cases"]
        self.assertTrue(first["has_input"] and first["has_output"])
        self.assertEqual(first["input_count"], 1)
        htm = next(item for item in first["workflows"] if item["key"] == "htm_before_after")
        htc = next(item for item in first["workflows"] if item["key"] == "htc_before_after")
        self.assertTrue(htm["ready"])
        self.assertEqual((htm["left"]["csv_count"], htm["right"]["csv_count"]), (1, 2))
        self.assertFalse(htc["ready"])
        self.assertIsNone(htc["left"]["csv_count"])
        self.assertFalse(second["has_output"])
        self.assertFalse(any(item["ready"] for item in second["workflows"]))
        with self.assertRaises(NotADirectoryError):
            describe_test_cases(self.root / "missing", config)

    def test_discovery_supports_exact_unicode_names_and_question_mark(self):
        for name in ("確認 01", "Scenario [01]", "Scenario_01", "scenario_02", "Scenario_001", "UT03"):
            (self.root / name).mkdir()
        (self.root / "Scenario_03").write_text("not a folder", encoding="utf-8")
        self.assertEqual([path.name for path in discover_test_cases(self.root, "確認 01")], ["確認 01"])
        self.assertEqual([path.name for path in discover_test_cases(self.root, "Scenario [01]")], ["Scenario [01]"])
        self.assertEqual([path.name for path in discover_test_cases(self.root, "Scenario_??")], ["Scenario_01", "scenario_02"])
        self.assertEqual([path.name for path in discover_test_cases(self.root)], ["UT03"])

    def test_match_all_pattern_discovers_children_and_recognizes_a_case_root(self):
        for name in ("Example One", "Example Two"):
            (self.root / name / "Output").mkdir(parents=True)
        self.assertEqual([path.name for path in discover_test_cases(self.root, "*", output_dir="Output")], ["Example One", "Example Two"])
        case = self.root / "Example One"
        self.assertEqual(discover_test_cases(case, "*", output_dir="Output"), [case])

    def test_missing_case_error_uses_saved_pattern(self):
        draft = read_compare_structure(self.path)
        draft["folders"]["case_pattern"] = "Scenario_??"
        save_compare_structure(draft, self.path)
        config = load_app_config(self.path)
        result = process_root(self.root, config=config)
        self.assertEqual(result.processed_count, 0)
        self.assertIn("Scenario_??", result.errors[0])
        with self.assertRaisesRegex(ValueError, "Scenario_\\?\\?"):
            load_ut_compare_workbooks(self.root, config)

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
            draft["folders"]["case_pattern"] = "Scenario*"
            with patch.object(app.jobs, "snapshot", return_value={"state": "running"}):
                with self.assertRaises(RuntimeError):
                    app.save_compare_structure(draft)
            self.assertEqual(self.path.read_bytes(), self.original)
            app.save_compare_structure(draft)
            self.assertEqual(app.config.folders.compare_dir, "New Results")
            self.assertEqual(app.config.folders.case_pattern, "Scenario*")
            self.assertEqual(app.config.compare_workflows[0].left_dir_name, draft["folders"]["before_htm_dir"])


if __name__ == "__main__":
    unittest.main()
