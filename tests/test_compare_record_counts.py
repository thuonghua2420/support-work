from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autocompare_tool.compare_record_counts import _infer_counts, _stored_counts, read_record_counts, store_record_counts

try:
    from openpyxl import load_workbook

    from autocompare_tool.app_config import load_app_config
    from autocompare_tool.compare_workbook_view import CompareWorkbookReference
    from autocompare_tool.excel_writer import write_compare_workbook_with_fixmes
    from autocompare_tool.fixme_replacements import apply_fixme_replacements
    from autocompare_tool.web_app import AutoCompareWebApplication
except ImportError:  # pragma: no cover - optional dependency guard for minimal environments.
    load_workbook = None


class CompareRecordCountMetadataTests(unittest.TestCase):
    def test_metadata_round_trip_keeps_unicode_sheet_names(self) -> None:
        workbook = SimpleNamespace(properties=SimpleNamespace(description=None))
        store_record_counts(workbook, {"顧客データ": (2, 1)})
        self.assertEqual({"顧客データ": (2, 1)}, _stored_counts(workbook.properties.description))
        self.assertEqual({}, _stored_counts("unrelated description"))

    def test_legacy_inference_detects_one_missing_record(self) -> None:
        rows = [
            (None, None, "Before 1", "After 1", "Before 2", "After 2"),
            ("id", "id", "1", "1", "2", None),
            ("name", "name", "A", "A", "B", None),
        ]

        class Sheet:
            def iter_rows(self, min_row, max_row=None, values_only=False):
                return iter(rows[min_row - 2:max_row - 1 if max_row else None])

        self.assertEqual((2, 1), _infer_counts(Sheet()))


@unittest.skipIf(load_workbook is None, "openpyxl is not installed")
class CompareRecordCountTests(unittest.TestCase):
    def test_exact_counts_survive_note_edit_without_adding_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before, after, output = self._paths(root)
            (before / "customers.csv").write_text("id,name\n1,A\n2,B\n", encoding="utf-8")
            (after / "customers.csv").write_text("id,name\n1,A\n", encoding="utf-8")
            result = write_compare_workbook_with_fixmes(before, after, output)

            workbook = load_workbook(output)
            self.assertEqual(["customers"], workbook.sheetnames)
            workbook.close()
            self.assertEqual([{
                "sheet_name": "customers", "left_count": 2, "right_count": 1,
                "difference": -1, "matches": False, "approximate": False,
            }], read_record_counts(output))

            apply_fixme_replacements(result.fixme_entries, {0: "Reviewed"})
            self.assertEqual((2, 1), (
                read_record_counts(output)[0]["left_count"],
                read_record_counts(output)[0]["right_count"],
            ))
            self.assertFalse(read_record_counts(output)[0]["approximate"])

    def test_older_workbook_uses_visible_record_pairs_as_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before, after, output = self._paths(root)
            (before / "customers.csv").write_text("id,name\n1,A\n2,B\n", encoding="utf-8")
            (after / "customers.csv").write_text("id,name\n1,A\n", encoding="utf-8")
            write_compare_workbook_with_fixmes(before, after, output)
            workbook = load_workbook(output)
            workbook.properties.description = None
            workbook.save(output)
            workbook.close()

            counts = read_record_counts(output)
            self.assertEqual((2, 1, True), (
                counts[0]["left_count"], counts[0]["right_count"], counts[0]["approximate"],
            ))

    def test_exact_metadata_counts_entirely_blank_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            before, after, output = self._paths(Path(temp_dir))
            (before / "blank.csv").write_text('name\n""\n', encoding="utf-8")
            (after / "blank.csv").write_text("name\n", encoding="utf-8")
            write_compare_workbook_with_fixmes(before, after, output)

            counts = read_record_counts(output)
            self.assertEqual((1, 0, False), (
                counts[0]["left_count"], counts[0]["right_count"], counts[0]["approximate"],
            ))

    def test_active_workbook_count_labels_follow_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before, after, _output = self._paths(root)
            (before / "customers.csv").write_text("id\n1\n", encoding="utf-8")
            (after / "customers.csv").write_text("id\n1\n", encoding="utf-8")
            config = load_app_config()
            output = root / config.workbooks.after_htc_vs_htm_file
            write_compare_workbook_with_fixmes(before, after, output)
            app = AutoCompareWebApplication()
            app._set_compare_result([], [CompareWorkbookReference("UT01", output, output.name)])

            summary = app.compare_record_counts_snapshot("0")
            self.assertEqual(("HTC sau", "HTM sau"), (summary["left_label"], summary["right_label"]))
            self.assertEqual((1, 0), (summary["sheet_count"], summary["mismatch_count"]))
            with self.assertRaisesRegex(ValueError, "không tồn tại"):
                app.compare_record_counts_snapshot("1")

    @staticmethod
    def _paths(root: Path) -> tuple[Path, Path, Path]:
        before = root / "before"
        after = root / "after"
        before.mkdir()
        after.mkdir()
        return before, after, root / "compare.xlsx"
