from __future__ import annotations

import random
import tempfile
import tracemalloc
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.utils import get_column_letter

from autocompare_tool.excel_compare import _CellState, _classify_change, compare_excel_workbooks
from autocompare_tool.excel_compare_store import ExcelCompareStore


_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SHEET_XML = "xl/worksheets/sheet1.xml"


class ExcelCompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.old = self.root / "old.xlsx"
        self.new = self.root / "new.xlsx"
        self.store = ExcelCompareStore()
        self.report_ids: list[str] = []
        self.addCleanup(self._delete_reports)

    def _delete_reports(self) -> None:
        for report_id in self.report_ids:
            self.store.delete(report_id)

    def compare(self, **kwargs):
        result = compare_excel_workbooks(self.old, self.new, store=self.store, **kwargs)
        self.report_ids.append(result.report_id)
        return result

    def test_reports_typed_values_rich_text_merged_cells_and_whitespace(self) -> None:
        when = datetime(2022, 3, 4, 5, 6)
        rich = CellRichText(["hello ", TextBlock(InlineFont(b=True), "world")])
        _save(self.old, {"Users": {
            "A1": "5", "A2": "trail ", "A3": "a  b", "A4": "#N/A", "A5": True, "A6": when,
            "A7": rich, "A8": "LF\nvalue", "A9": "same", "A10": False,
        }}, merge="A9:B9")
        _save(self.new, {"Users": {
            "A1": 5, "A2": "trail", "A3": "a b", "A4": "#REF!", "A5": 1, "A6": str(when),
            "A7": "hello world", "A8": "LF\r\nvalue", "A9": "same", "A10": "FALSE",
        }})

        result = self.compare()
        total, rows = self.store.query(result.report_id, 0)
        self.assertEqual(8, total)
        self.assertEqual(8, result.difference_count)
        self.assertEqual({
            "A1": ("5 (văn bản)", "5 (số)", "kind"),
            "A2": ('"trail "', '"trail"', "changed"),
            "A3": ('"a  b"', '"a b"', "changed"),
            "A4": ("#N/A", "#REF!", "changed"),
            "A5": ("TRUE", "1", "changed"),
            "A6": (f"{when} (ngày giờ)", f"{when} (văn bản)", "kind"),
            "A8": ('"LF\nvalue"', '"LF\n\nvalue"', "changed"),
            "A10": ("FALSE (TRUE/FALSE)", "FALSE (văn bản)", "kind"),
        }, {row["coord"]: (row["old"], row["new"], row["change_type"]) for row in rows})
        self.assertEqual({"changed": 5, "added": 0, "removed": 0, "kind": 3, "formula": 0},
                         result.sheets[0].counts_by_type)
        self.assertEqual({"old.xlsx", "new.xlsx"}, {path.name for path in self.root.iterdir()})

    def test_formula_text_and_cached_results(self) -> None:
        _save(self.old, {"S": {"A1": "=1+2", "B2": "=2+2", "C1": "=3+2", "D1": "=1"}})
        _save(self.new, {"S": {"A1": "=1+2", "B2": "=2*2", "C1": "=3+2", "D1": "=1"}})
        _rewrite_sheet(self.old, cache={"A1": 3, "B2": 4, "C1": 5, "D1": 1})
        _rewrite_sheet(self.new, cache={"A1": 30, "B2": 4, "D1": 1})

        result = self.compare()
        total, rows = self.store.query(result.report_id, 0)
        self.assertEqual(2, total)
        self.assertEqual([
            ("A1", "=1+2 → 3", "=1+2 → 30", "formula"),
            ("B2", "=2+2 → 4", "=2*2 → 4", "formula"),
        ], [(row["coord"], row["old"], row["new"], row["change_type"]) for row in rows])

    def test_classifies_differing_states(self) -> None:
        for old, new, expected in (
            (_CellState("text", "x"), _CellState("text", "y"), "changed"),
            (_CellState("blank"), _CellState("formula", "=1", 1), "added"),
            (_CellState("formula", "=1", 1), _CellState("blank"), "removed"),
            (_CellState("number", 5), _CellState("text", "5"), "kind"),
            (_CellState("error", "#N/A"), _CellState("text", "#N/A"), "kind"),
            (_CellState("formula", "=1", 1), _CellState("formula", "=1", 2), "formula"),
            (_CellState("formula", "=1"), _CellState("text", "=1"), "formula"),
        ):
            with self.subTest(old=old, new=new):
                self.assertEqual(expected, _classify_change(old, new))

    def test_pairs_names_first_then_pairs_by_position_and_reports_one_sided_sheets(self) -> None:
        _save(self.old, {"Before": {"A1": "old"}, "Shared": {"A1": "same"}, "Old tail": {"A1": "old only"}})
        _save(self.new, {"Shared": {"A1": "same"}, "After": {"A1": "new"}})

        paired = self.compare()
        self.assertEqual(3, paired.sheet_pair_count)
        self.assertEqual(
            [(0, "Before", "After", "position"), (1, "Shared", "Shared", "name"), (2, "Old tail", None, "old_only")],
            [(sheet.index, sheet.old_name, sheet.new_name, sheet.pairing) for sheet in paired.sheets],
        )
        self.assertEqual((2, 0, 1),
                         (paired.difference_count, paired.missing_old_sheet_count, paired.missing_new_sheet_count))
        self.assertEqual("removed", self.store.query(paired.report_id, 2)[1][0]["change_type"])

        separate = self.compare(pair_by_position=False)
        self.assertEqual(["old_only", "name", "old_only", "new_only"], [sheet.pairing for sheet in separate.sheets])
        self.assertEqual((3, 1, 2), (separate.difference_count,
                                    separate.missing_old_sheet_count, separate.missing_new_sheet_count))
        self.assertEqual("added", self.store.query(separate.report_id, 3)[1][0]["change_type"])

    def test_identical_files_and_missing_empty_sheet(self) -> None:
        _save(self.old, {"Empty": {}, "Shared": {"B3": "same"}})

        identical = compare_excel_workbooks(self.old, self.old, store=self.store)
        self.report_ids.append(identical.report_id)
        self.assertTrue(identical.identical)
        self.assertEqual(0, identical.difference_count)
        empty = identical.sheets[0]
        self.assertEqual((0, 0, 0, 0), (empty.old_rows, empty.old_columns, empty.new_rows, empty.new_columns))
        self.assertEqual((0, []), self.store.query(identical.report_id, 0))

        _save(self.new, {"Shared": {"B3": "same"}})
        missing = self.compare()
        self.assertFalse(missing.identical)
        self.assertEqual(1, missing.missing_new_sheet_count)
        self.assertEqual(0, missing.difference_count)

    def test_ignores_incorrect_or_absent_dimensions_and_handles_ragged_rows(self) -> None:
        _save(self.old, {"S": {"A1": "old title", "H1": "previous H", "A3": "same", "H5": "gone"}})
        _save(self.new, {"S": {"A1": "new title", "A3": "same", "H4": "new H", "J7": "tail"}})
        _rewrite_sheet(self.old, dimension="A1:A1")
        _rewrite_sheet(self.new, dimension=None)
        for path, expected in ((self.old, (1, 1)), (self.new, (None, None))):
            book = load_workbook(path, read_only=True)
            try:
                self.assertEqual(expected, (book.active.max_row, book.active.max_column))
            finally:
                book.close()

        result = self.compare()
        sheet = result.sheets[0]
        self.assertEqual((5, 8, 7, 10), (sheet.old_rows, sheet.old_columns, sheet.new_rows, sheet.new_columns))
        self.assertEqual(5, sheet.difference_count)
        _, rows = self.store.query(result.report_id, 0)
        self.assertEqual(
            [("A1", "new title"), ("H1", "previous H"), ("H4", "previous H"), ("H5", "previous H"), ("J7", "")],
            [(row["coord"], row["header"]) for row in rows],
        )
        self.assertEqual((
            {"column": "H", "header": "previous H", "count": 3},
            {"column": "A", "header": "new title", "count": 1},
            {"column": "J", "header": "", "count": 1},
        ), sheet.top_columns)

    def test_truncates_details_across_sheets_and_counts_all_columns(self) -> None:
        _save(self.old, {"First": {}, "Second": {}, "Third": {}})
        _save(self.new, {
            "First": {"A1": "first"},
            "Second": {f"{get_column_letter(col)}1": f"title {col}" for col in range(1, 13)},
            "Third": {"A1": "last"},
        })

        result = self.compare(max_detail_rows=2)
        self.assertTrue(result.details_truncated)
        self.assertEqual(14, result.difference_count)
        self.assertEqual([False, True, True], [sheet.details_truncated for sheet in result.sheets])
        self.assertEqual([1, 12, 1], [sheet.counts_by_type["added"] for sheet in result.sheets])
        self.assertEqual([1, 1, 0], [self.store.query(result.report_id, sheet)[0] for sheet in range(3)])
        self.assertEqual([
            {"column": get_column_letter(col), "header": f"title {col}", "count": 1}
            for col in range(1, 11)
        ], list(result.sheets[1].top_columns))

    def test_logs_progress_in_a_sparse_sheet(self) -> None:
        _save(self.old, {"S": {}})
        _save(self.new, {"S": {"A50000": "end"}})
        messages = []

        result = self.compare(log=messages.append)

        self.assertEqual(1, result.difference_count)
        self.assertIn("[1/1] Sheet S: đã duyệt 50,000 hàng...", messages)
        self.assertIn("[1/1] Sheet S: 1 ô sai khác.", messages)

    def test_matches_an_eager_oracle_on_random_ragged_workbooks(self) -> None:
        rng = random.Random(1438)
        for path in (self.old, self.new):
            _save(path, {
                name: {
                    f"{get_column_letter(col)}{row}": rng.choice(["cat", "dog", 2, 3])
                    for row in range(1, 31) for col in range(1, 9) if rng.random() < density
                }
                for name, density in (("Dense", 0.8), ("Sparse", 0.2), ("Empty", 0))
            })
        result = self.compare()
        old_book, new_book = load_workbook(self.old), load_workbook(self.new)
        self.addCleanup(old_book.close)
        self.addCleanup(new_book.close)
        for sheet in result.sheets:
            old, new = old_book[sheet.old_name], new_book[sheet.new_name]
            expected = {}
            for row in range(1, max(old.max_row, new.max_row) + 1):
                for col in range(1, max(old.max_column, new.max_column) + 1):
                    a, b = old.cell(row, col), new.cell(row, col)
                    if a.value != b.value:
                        expected[a.coordinate] = tuple("" if cell.value is None else str(cell.value) for cell in (a, b))
            total, rows = self.store.query(result.report_id, sheet.index, limit=500)
            self.assertEqual(len(expected), total)
            self.assertEqual(expected, {row["coord"]: (row["old"], row["new"]) for row in rows})

    def test_query_paging_literal_search_and_filters(self) -> None:
        _save(self.old, {"S": {"C1": "old-only", "B2": "needle-OLD"}})
        _save(self.new, {"S": {
            "A1": "header%_\\", "A2": "left", "B1": "label",
            "B2": "value%_\\", "D2": "valueXXY",
            **{f"F{row}": "item" for row in range(1, 511)},
        }})
        report = self.compare().report_id

        total, rows = self.store.query(report, 0, offset=1, limit=2)
        self.assertEqual(516, total)
        self.assertEqual(["B1", "C1"], [row["coord"] for row in rows])
        self.assertEqual(500, len(self.store.query(report, 0, offset=-1, limit=501)[1]))
        self.assertEqual(["A1"], [row["coord"] for row in self.store.query(report, 0, limit=0)[1]])
        self.assertEqual((516, []), self.store.query(report, 0, offset=10**30))
        for term in ("%", "_", "\\", "%_\\"):
            with self.subTest(term=term):
                total, rows = self.store.query(report, 0, search=term)
                self.assertEqual(3, total)
                self.assertEqual(["A1", "A2", "B2"], [row["coord"] for row in rows])
        self.assertEqual("B2", self.store.query(report, 0, search="needle")[1][0]["coord"])
        self.assertEqual("B2", self.store.query(report, 0, search="b2")[1][0]["coord"])
        self.assertEqual((0, []), self.store.query(report, 0, search="' OR 1=1 --"))
        self.assertEqual(1, self.store.query(report, 0, change_types=["removed"])[0])
        total, rows = self.store.query(report, 0, change_types=["changed", "removed"], column="b")
        self.assertEqual(1, total)
        self.assertEqual("B2", rows[0]["coord"])
        self.assertEqual("B", rows[0]["column"])

    def test_keeps_three_finished_reports_and_deletes_evicted_files(self) -> None:
        _save(self.old, {"Empty": {}})
        _save(self.new, {"Empty": {}})
        reports = [self.compare().report_id for _ in range(4)]

        self.assertFalse(self.store._path(reports[0]).exists())
        for report in reports[1:]:
            self.assertTrue(self.store._path(report).is_file())
        with self.assertRaisesRegex(FileNotFoundError, "hết hạn"):
            self.store.query(reports[0], 0)
        with self.assertRaisesRegex(FileNotFoundError, "không tồn tại"):
            self.store.query("../unknown", 0)
        self.store.delete(reports[1])
        self.assertFalse(self.store._path(reports[1]).exists())

    def test_cancellation_discards_partial_report_and_releases_workbooks(self) -> None:
        _save(self.old, {"S": {}})
        _save(self.new, {"S": {
            f"{get_column_letter(col)}{row}": col for row in range(1, 252) for col in range(1, 6)
        }})
        spool_paths = set(self.store._path("unused").parent.iterdir())

        with patch.object(self.store, "add_batch", wraps=self.store.add_batch) as add_batch:
            def cancel() -> None:
                if add_batch.called:
                    raise InterruptedError("cancelled")

            with self.assertRaisesRegex(InterruptedError, "cancelled"):
                self.compare(cancel=cancel)
            add_batch.assert_called_once()
        self.assertEqual(spool_paths, set(self.store._path("unused").parent.iterdir()))
        self.old.unlink()
        self.new.unlink()

    def test_validates_inputs(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.compare()
        self.old.touch()
        text_path = self.root / "new.txt"
        text_path.touch()
        with self.assertRaisesRegex(ValueError, "XLSX"):
            compare_excel_workbooks(self.old, text_path, store=self.store)

    def test_streaming_memory_on_60000_cells_per_workbook(self) -> None:
        for path in (self.old, self.new):
            book = Workbook(write_only=True)
            sheet = book.create_sheet("Large")
            for row in range(3_000):
                sheet.append([row] * 20)
            book.save(path)

        tracemalloc.start()
        try:
            result = self.compare()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertTrue(result.identical)
        self.assertEqual((3_000, 20), (result.sheets[0].new_rows, result.sheets[0].new_columns))
        self.assertLess(peak, 60 * 1024 * 1024)


def _save(path: Path, cells_by_sheet: dict, *, merge: str | None = None) -> None:
    book = Workbook()
    book.remove(book.active)
    for name, cells in cells_by_sheet.items():
        sheet = book.create_sheet(name)
        for coord, value in cells.items():
            sheet[coord] = value
        if merge:
            sheet.merge_cells(merge)
    book.save(path)


def _rewrite_sheet(path: Path, *, dimension: str | None = "A1:D1", cache: dict | None = None) -> None:
    """Emulate stale worksheet dimensions or formula caches saved by Excel."""
    temporary = path.with_suffix(".tmp")
    with ZipFile(path) as source, ZipFile(temporary, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == _SHEET_XML:
                sheet = ET.fromstring(data)
                node = sheet.find(f"{_SHEET_NS}dimension")
                if dimension is None:
                    sheet.remove(node)
                else:
                    node.set("ref", dimension)
                for coord, value in (cache or {}).items():
                    cell = sheet.find(f".//{_SHEET_NS}c[@r='{coord}']")
                    cell.find(f"{_SHEET_NS}v").text = str(value)
                data = ET.tostring(sheet)
            target.writestr(item, data)
    temporary.replace(path)


if __name__ == "__main__":
    unittest.main()
