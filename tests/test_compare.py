from __future__ import annotations

import unittest
import random
import tempfile
import time
from pathlib import Path

from autocompare_tool.compare import build_sheet_comparison, cell_value, cell_values_equal
from autocompare_tool.csv_table import CsvTable


class CompareTests(unittest.TestCase):
    def test_partial_first_column_key_matches_do_not_create_extra_pairs_without_key(self) -> None:
        before = CsvTable(["seq"], [{"seq": value} for value in ["1", "2", "3", "4"]])
        after = CsvTable(["seq"], [{"seq": value} for value in ["1", "2", "30", "40"]])

        comparison = build_sheet_comparison("customers", before, after)

        self.assertEqual(len(comparison.pairs), 4)
        self.assertEqual([cell_value(pair.before, "seq") for pair in comparison.pairs], ["1", "2", "3", "4"])
        self.assertEqual([cell_value(pair.after, "seq") for pair in comparison.pairs], ["1", "2", "30", "40"])

    def test_update_maps_same_first_column_key_without_key(self) -> None:
        before = CsvTable(["id", "name"], [{"id": "5", "name": "old"}])
        after = CsvTable(["id", "name"], [{"id": "5", "name": "new"}])

        comparison = build_sheet_comparison("sample.csv", before, after)

        self.assertEqual(len(comparison.pairs), 1)
        self.assertEqual(cell_value(comparison.pairs[0].before, "id"), "5")
        self.assertEqual(cell_value(comparison.pairs[0].after, "id"), "5")
        self.assertEqual(cell_value(comparison.pairs[0].before, "name"), "old")
        self.assertEqual(cell_value(comparison.pairs[0].after, "name"), "new")

    def test_extra_after_records_are_paired_by_position_without_key(self) -> None:
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

    def test_extra_before_records_are_paired_by_position_without_key(self) -> None:
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

    def test_duplicate_first_column_values_stay_in_file_order_without_key(self) -> None:
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

    def test_same_length_mismatched_first_column_keys_compare_by_record_order_without_key(self) -> None:
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

    def test_same_length_different_first_header_compares_by_record_order_without_key(self) -> None:
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


class KeyCompareTests(unittest.TestCase):
    def table(self, keys):
        return CsvTable(["id", "value"], [{"id": key, "value": f"value-{key}"} for key in keys])

    def compare(self, before, after):
        result = build_sheet_comparison("orders", before, after, key_columns=("ID",))
        self.assertEqual(result.match_mode, "key")
        self.assertEqual(result.fallback_reason, "")
        self.assert_invariants(result, before, after)
        return result

    def assert_invariants(self, result, before, after):
        union = {row["id"] for row in before.rows + after.rows}
        self.assertEqual(sum(result.status_counts().values()), len(union))
        self.assertEqual([cell_value(pair.before or pair.after, "id") for pair in result.pairs], sorted(union))
        for pair in result.pairs:
            if pair.before is not None and pair.after is not None:
                self.assertEqual(pair.before["id"], pair.after["id"])
        for side, table in (("before", before), ("after", after)):
            indices = [getattr(pair, side + "_index") for pair in result.pairs if getattr(pair, side) is not None]
            self.assertEqual(sorted(indices), list(range(len(table.rows))))
            self.assertTrue(all(getattr(pair, side) is table.rows[getattr(pair, side + "_index")]
                                for pair in result.pairs if getattr(pair, side) is not None))

    def test_exact_regression(self):
        before = self.table(["234", "387", "634"])
        after = self.table(["135", "234", "375", "634"])
        after.rows[-1]["value"] = "updated"
        result = self.compare(before, after)
        self.assertEqual([(cell_value(pair.before or pair.after, "id"), pair.status) for pair in result.pairs], [
            ("135", "INSERT"), ("234", "UNCHANGED"), ("375", "INSERT"), ("387", "DELETE"), ("634", "UPDATE"),
        ])
        self.assertEqual(result.status_counts(), {"INSERT": 2, "DELETE": 1, "UPDATE": 1, "UNCHANGED": 1})

    def test_insert_delete_combinations_and_empty_sides(self):
        cases = [
            ([], []), ([], ["1", "2"]), (["1", "2"], []), (["2"], ["1", "2"]),
            (["1", "2"], ["2"]), (["1"], ["1", "2"]), (["1", "2"], ["1"]),
            (["3"], ["1", "2", "3"]), (["1", "2", "3"], ["3"]),
            (["1", "4"], ["1", "2", "3", "4"]), (["1", "2", "3", "4"], ["1", "4"]),
            (["1", "3"], ["2", "4"]), (["2", "4"], ["1", "3"]),
            (["1"], [str(i) for i in range(100)]), ([str(i) for i in range(100)], ["1"]),
            (["3", "1", "2"], ["2", "3", "1"]),
        ]
        for before, after in cases:
            with self.subTest(before=before, after=after):
                self.compare(self.table(before), self.table(after))
        for before, after in ((CsvTable([], []), self.table(["2", "1"])),
                              (self.table(["2", "1"]), CsvTable([], [])), (CsvTable([], []), CsvTable([], []))):
            with self.subTest(missing_header=True, before=before, after=after):
                result = self.compare(before, after)
                self.assertTrue(all(pair.status == ("INSERT" if not before.rows else "DELETE") for pair in result.pairs))

    def test_key_change_is_delete_plus_insert(self):
        result = self.compare(self.table(["1"]), self.table(["2"]))
        self.assertEqual([pair.status for pair in result.pairs], ["DELETE", "INSERT"])

    def test_order_is_independent_of_input_and_equal_data_never_updates(self):
        rng = random.Random(234)
        before, after = self.table([str(i) for i in range(150)]), self.table([str(i) for i in range(50, 200)])
        baseline = self.compare(before, after)
        expected = [(pair.before, pair.after, pair.status) for pair in baseline.pairs]
        for _ in range(5):
            rng.shuffle(before.rows)
            rng.shuffle(after.rows)
            result = self.compare(before, after)
            self.assertEqual([(pair.before, pair.after, pair.status) for pair in result.pairs], expected)
        same = CsvTable(before.headers, list(reversed(before.rows)))
        self.assertEqual(self.compare(before, same).status_counts()["UNCHANGED"], 150)

    def test_composite_key_preserves_raw_text_and_casefolds_header_lookup(self):
        before = CsvTable(["ID", "Line", "value"], [
            {"ID": "1", "Line": "2", "value": "two"},
            {"ID": "001", "Line": "1", "value": "zero"},
            {"ID": "1", "Line": "10", "value": "ten"},
        ])
        after = CsvTable(before.headers, list(reversed(before.rows)))
        result = build_sheet_comparison("orders", before, after, key_columns=("id", "LINE"))
        self.assertEqual(result.match_mode, "key")
        self.assertEqual([(p.before["ID"], p.before["Line"]) for p in result.pairs], [("001", "1"), ("1", "10"), ("1", "2")])
        self.assertEqual(result.status_counts()["UNCHANGED"], 3)

    def test_order_matches_csv_order_including_special_and_multiline_keys(self):
        from autocompare_tool.csv_order import _ordered_csv
        from autocompare_tool.csv_table import read_csv_table
        from autocompare_tool.dbeaver_csv import write_dbeaver_csv
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "orders.csv"
            keys = ['日本', 'a,b', 'a"b', 'a\r\nb', '001', '1', ' 2 ']
            write_dbeaver_csv(path, ["id", "value"], [[key, key] for key in keys])
            before = read_csv_table(path)
            _, ordered = _ordered_csv(path, ("ID",))
            path.write_bytes(ordered)
            result = self.compare(before, before)
            self.assertEqual([pair.before["id"] for pair in result.pairs], [row["id"] for row in read_csv_table(path).rows])

    def test_status_preserves_null_empty_missing_column_crlf_and_skipped_metadata(self):
        cases = [(None, "NULL", "UPDATE"), (None, "", "UPDATE"), ("a\r\nb", "a\nb", "UPDATE"),
                 ("", "", "UNCHANGED"), (None, None, "UNCHANGED"), ('a,b"c', 'a,b"c', "UNCHANGED")]
        for left, right, status in cases:
            with self.subTest(left=left, right=right):
                before, after = self.table(["1"]), self.table(["1"])
                before.rows[0]["value"], after.rows[0]["value"] = left, right
                self.assertEqual(self.compare(before, after).pairs[0].status, status)
        before, after = self.table(["1"]), self.table(["1"])
        after.headers.append("extra")
        after.rows[0]["extra"] = ""
        self.assertEqual(self.compare(before, after).pairs[0].status, "UPDATE")
        before, after = self.table(["1"]), self.table(["1"])
        before.headers.append("DataState")
        before.rows[0]["DataState"] = "ignored"
        self.assertEqual(self.compare(before, after).pairs[0].status, "UNCHANGED")

    def test_invalid_keys_fall_back_without_losing_positional_pairs(self):
        good = self.table(["2", "1"])
        invalid = [
            (self.table([None, "1"]), ("id",), "NULL/blank"),
            (self.table(["", "1"]), ("id",), "NULL/blank"),
            (self.table([" \t", "1"]), ("id",), "NULL/blank"),
            (self.table(["1", "1"]), ("id",), "Duplicate"),
            (CsvTable(["other"], [{"other": "1"}]), ("id",), "header"),
            (CsvTable(["other"], []), ("id",), "header"),
            (good, ("id", "ID"), "trùng"),
            (CsvTable(["id", "ID"], [{"id": "1", "ID": "2"}]), ("id",), "trùng"),
            (good, None, "[update_compare_keys]"),
        ]
        for bad, key_columns, reason in invalid:
            for side in ("Trái", "Phải"):
                with self.subTest(reason=reason, side=side, bad=bad):
                    before, after = (bad, good) if side == "Trái" else (good, bad)
                    result = build_sheet_comparison("orders", before, after, key_columns=key_columns)
                    self.assertEqual(result.match_mode, "position")
                    self.assertIn(reason, result.fallback_reason)
                    if key_columns and reason != "trùng":
                        self.assertIn(side, result.fallback_reason)
                    self.assertEqual([p.before for p in result.pairs], before.rows + [None] * max(0, len(after.rows) - len(before.rows)))
                    self.assertEqual([p.after for p in result.pairs], after.rows + [None] * max(0, len(before.rows) - len(after.rows)))

    def test_fallback_diagnostic_includes_source_record_key_and_physical_lines(self):
        bad = CsvTable(["id"], [{"id": "a\nb"}, {"id": "a\nb"}], [(1, 1), (2, 3), (4, 5)])
        result = build_sheet_comparison("orders", bad, self.table(["1"]), key_columns=("id",))
        for expected in ("Trái", "Record CSV: 2", "4–5", "a\\nb", "trước đó: 1"):
            self.assertIn(expected, result.fallback_reason)

    def test_8000_records_per_side_merge_in_under_one_second(self):
        before = self.table([str(i) for i in range(0, 16000, 2)])
        after = self.table([str(i) for i in range(1, 16000, 2)])
        started = time.perf_counter()
        result = build_sheet_comparison("orders", before, after, key_columns=("id",))
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)
        self.assert_invariants(result, before, after)
        self.assertEqual(result.status_counts(), {"INSERT": 8000, "DELETE": 8000, "UPDATE": 0, "UNCHANGED": 0})


if __name__ == "__main__":
    unittest.main()
