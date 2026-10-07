from __future__ import annotations

import unittest

from autocompare_tool.compare import build_sheet_comparison, cell_value, cell_values_equal
from autocompare_tool.csv_table import CsvTable


class CompareTests(unittest.TestCase):
    def test_partial_first_column_key_matches_do_not_create_extra_pairs(self) -> None:
        before = CsvTable(["seq"], [{"seq": value} for value in ["1", "2", "3", "4"]])
        after = CsvTable(["seq"], [{"seq": value} for value in ["1", "2", "30", "40"]])

        comparison = build_sheet_comparison("customers", before, after)

        self.assertEqual(len(comparison.pairs), 4)
        self.assertEqual([cell_value(pair.before, "seq") for pair in comparison.pairs], ["1", "2", "3", "4"])
        self.assertEqual([cell_value(pair.after, "seq") for pair in comparison.pairs], ["1", "2", "30", "40"])

    def test_update_maps_same_first_column_key(self) -> None:
        before = CsvTable(["id", "name"], [{"id": "5", "name": "old"}])
        after = CsvTable(["id", "name"], [{"id": "5", "name": "new"}])

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual(len(comparison.pairs), 1)
        self.assertEqual(cell_value(comparison.pairs[0].before, "id"), "5")
        self.assertEqual(cell_value(comparison.pairs[0].after, "id"), "5")
        self.assertEqual(cell_value(comparison.pairs[0].before, "name"), "old")
        self.assertEqual(cell_value(comparison.pairs[0].after, "name"), "new")

    def test_extra_after_records_are_paired_by_position(self) -> None:
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
        self.assertEqual([cell_value(pair.before, "id") for pair in comparison.pairs], ["5", "", ""])

    def test_extra_before_records_are_paired_by_position(self) -> None:
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
        self.assertEqual([cell_value(pair.before, "id") for pair in comparison.pairs], ["2", "5", "7"])

    def test_duplicate_first_column_values_stay_in_file_order(self) -> None:
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

    def test_same_length_mismatched_first_column_keys_compare_by_record_order(self) -> None:
        before = CsvTable(
            ["id", "created_at", "name"],
            [
                {"id": "100", "created_at": "2026-01-01 08:00:00", "name": "Alice old"},
                {"id": "101", "created_at": "2026-01-01 08:01:00", "name": "Bob old"},
            ],
        )
        after = CsvTable(
            ["id", "created_at", "name"],
            [
                {"id": "200", "created_at": "2026-01-02 09:00:00", "name": "Alice new"},
                {"id": "201", "created_at": "2026-01-02 09:01:00", "name": "Bob new"},
            ],
        )

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual([cell_value(pair.before, "id") for pair in comparison.pairs], ["100", "101"])
        self.assertEqual([cell_value(pair.after, "id") for pair in comparison.pairs], ["200", "201"])
        self.assertEqual([cell_value(pair.before, "name") for pair in comparison.pairs], ["Alice old", "Bob old"])
        self.assertEqual([cell_value(pair.after, "name") for pair in comparison.pairs], ["Alice new", "Bob new"])

    def test_same_length_different_first_header_compares_by_record_order(self) -> None:
        before = CsvTable(["old_id", "name"], [{"old_id": "10", "name": "before"}])
        after = CsvTable(["new_id", "name"], [{"new_id": "20", "name": "after"}])

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual(cell_value(comparison.pairs[0].before, "name"), "before")
        self.assertEqual(cell_value(comparison.pairs[0].after, "name"), "after")

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

    def test_exact_cell_comparison_keeps_null_empty_missing_and_line_endings_distinct(self) -> None:
        self.assertFalse(cell_values_equal({"value": None}, {"value": "NULL"}, "value"))
        self.assertFalse(cell_values_equal({"value": None}, {"value": ""}, "value"))
        self.assertFalse(cell_values_equal({}, {"value": ""}, "value"))
        self.assertFalse(cell_values_equal(None, {"value": ""}, "value"))
        self.assertFalse(cell_values_equal({"value": "a\r\nb"}, {"value": "a\nb"}, "value"))
        self.assertTrue(cell_values_equal({"value": " exact "}, {"value": " exact "}, "value"))


if __name__ == "__main__":
    unittest.main()
