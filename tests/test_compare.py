from __future__ import annotations

import unittest

from autocompare_tool.compare import build_sheet_comparison, cell_value
from autocompare_tool.csv_table import CsvTable


class CompareTests(unittest.TestCase):
    def test_update_maps_same_first_column_key(self) -> None:
        before = CsvTable(["id", "name"], [{"id": "5", "name": "old"}])
        after = CsvTable(["id", "name"], [{"id": "5", "name": "new"}])

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual(len(comparison.pairs), 1)
        self.assertEqual(cell_value(comparison.pairs[0].before, "id"), "5")
        self.assertEqual(cell_value(comparison.pairs[0].after, "id"), "5")
        self.assertEqual(cell_value(comparison.pairs[0].before, "name"), "old")
        self.assertEqual(cell_value(comparison.pairs[0].after, "name"), "new")

    def test_insert_keeps_matching_key_aligned(self) -> None:
        before = CsvTable(["id", "name"], [{"id": "5", "name": "exists"}])
        after = CsvTable(
            ["id", "name"],
            [
                {"id": "2", "name": "inserted-2"},
                {"id": "5", "name": "exists"},
                {"id": "7", "name": "inserted-7"},
            ],
        )

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual([cell_value(pair.after, "id") for pair in comparison.pairs], ["2", "5", "7"])
        self.assertEqual([cell_value(pair.before, "id") for pair in comparison.pairs], ["", "5", ""])

    def test_delete_appends_before_only_rows(self) -> None:
        before = CsvTable(
            ["id", "name"],
            [
                {"id": "2", "name": "deleted-2"},
                {"id": "5", "name": "kept"},
                {"id": "7", "name": "deleted-7"},
            ],
        )
        after = CsvTable(["id", "name"], [{"id": "5", "name": "kept"}])

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual([cell_value(pair.after, "id") for pair in comparison.pairs], ["5", "", ""])
        self.assertEqual([cell_value(pair.before, "id") for pair in comparison.pairs], ["5", "2", "7"])

    def test_duplicate_keys_use_occurrence_order(self) -> None:
        before = CsvTable(
            ["id", "value"],
            [{"id": "5", "value": "before-1"}, {"id": "5", "value": "before-2"}],
        )
        after = CsvTable(
            ["id", "value"],
            [{"id": "5", "value": "after-1"}, {"id": "5", "value": "after-2"}],
        )

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual(cell_value(comparison.pairs[0].before, "value"), "before-1")
        self.assertEqual(cell_value(comparison.pairs[0].after, "value"), "after-1")
        self.assertEqual(cell_value(comparison.pairs[1].before, "value"), "before-2")
        self.assertEqual(cell_value(comparison.pairs[1].after, "value"), "after-2")

    def test_column_union_prioritizes_after_headers(self) -> None:
        before = CsvTable(["id", "legacy"], [{"id": "1", "legacy": "x"}])
        after = CsvTable(["id", "current"], [{"id": "1", "current": "y"}])

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual(comparison.columns, ["id", "current", "legacy"])

    def test_source_metadata_columns_are_skipped(self) -> None:
        before = CsvTable(
            ["id", "ValidationErrors", "HasErrors", "TargetProperties", "DataState", "name"],
            [{"id": "1", "name": "before"}],
        )
        after = CsvTable(
            ["id", "ValidationErrors", "HasErrors", "TargetProperties", "DataState", "name"],
            [{"id": "1", "name": "after"}],
        )

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual(comparison.columns, ["id", "name"])


if __name__ == "__main__":
    unittest.main()
