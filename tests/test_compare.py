from __future__ import annotations

import unittest

from autocompare_tool.compare import build_sheet_comparison, cell_value
from autocompare_tool.csv_table import CsvTable


class CompareTests(unittest.TestCase):
    def test_shared_keys_stay_aligned_when_order_or_membership_changes(self) -> None:
        for after_ids, expected_before, expected_after in [
            (["C001", "C002", "C004"], ["C001", "C002", "C004", "C003"],
             ["C001", "C002", "C004", ""]),
            (["C004", "C002", "C001", "C003"], ["C004", "C002", "C001", "C003"],
             ["C004", "C002", "C001", "C003"]),
            (["C001", "C002", "C004", "C005"], ["C001", "C002", "C004", "", "C003"],
             ["C001", "C002", "C004", "C005", ""]),
        ]:
            with self.subTest(after_ids=after_ids):
                before = CsvTable(["id"], [{"id": key} for key in ["C001", "C002", "C003", "C004"]])
                after = CsvTable(["id"], [{"id": key} for key in after_ids])

                comparison = build_sheet_comparison("customers", before, after)

                self.assertEqual([cell_value(pair.before, "id") for pair in comparison.pairs], expected_before)
                self.assertEqual([cell_value(pair.after, "id") for pair in comparison.pairs], expected_after)

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


if __name__ == "__main__":
    unittest.main()
