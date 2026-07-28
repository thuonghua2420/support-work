from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocompare_tool.db_roundtrip import (
    DatabaseSettings,
    TableColumn,
    _process_csv_folder,
    _reorder_csv_by_db_columns,
)
from autocompare_tool.dbeaver_csv import DbeaverCsv


class DbReorderTests(unittest.TestCase):
    def test_reorder_uses_db_order_and_preserves_values(self) -> None:
        table = DbeaverCsv(
            headers=["name", "id", "empty_value", "null_value", "computed_value"],
            rows=[["Alice", "10", "", None, "A-10"]],
        )
        columns = [
            _column("id", is_identity=True),
            _column("name"),
            _column("computed_value", is_computed=True),
            _column("empty_value"),
            _column("null_value"),
        ]

        headers, rows = _reorder_csv_by_db_columns(table, columns)

        self.assertEqual(headers, ["id", "name", "computed_value", "empty_value", "null_value"])
        self.assertEqual(rows, [["10", "Alice", "A-10", "", None]])

    def test_reorder_formats_datetime_and_four_decimal_numbers(self) -> None:
        table = DbeaverCsv(
            headers=["amount", "created_at", "name"],
            rows=[
                ["3456.0", "2026-06-29 12:34:56", "Alice"],
                ["4567.35", "06/29/2026 1:02 PM", "Bob"],
                ["2345.698", "2026/06/29", "Carol"],
                ["2345.9867", "2026-06-29T12:34:56.789123", "Dave"],
            ],
        )
        columns = [
            _column("name"),
            _column("amount", type_name="numeric"),
            _column("created_at", type_name="datetime"),
        ]

        headers, rows = _reorder_csv_by_db_columns(table, columns)

        self.assertEqual(headers, ["name", "amount", "created_at"])
        self.assertEqual(
            rows,
            [
                ["Alice", "3456.0000", "2026-06-29 12:34:56.000"],
                ["Bob", "4567.3500", "2026-06-29 13:02:00.000"],
                ["Carol", "2345.6980", "2026-06-29 00:00:00.000"],
                ["Dave", "2345.9867", "2026-06-29 12:34:56.789"],
            ],
        )

    def test_process_csv_folder_skips_csv_without_matching_db_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "missing_table.csv"
            csv_path.write_text("id,name\r\n\"1\",\"Alice\"\r\n", encoding="utf-8")
            messages: list[str] = []

            result = _process_csv_folder(
                FakeConnection([]),
                DatabaseSettings(server=".", database="sample"),
                root,
                messages.append,
            )

            self.assertEqual(result.csv_results, [])
            self.assertEqual(result.errors, [])
            self.assertIn("bỏ qua vì không tìm thấy table: dbo.missing_table", messages[-1])


class FakeConnection:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def cursor(self) -> "FakeCursor":
        return FakeCursor(self.rows)

    def rollback(self) -> None:
        raise AssertionError("skip should not rollback")


class FakeCursor:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def execute(self, *_args: object) -> None:
        return None

    def fetchall(self) -> list[object]:
        return self.rows


def _column(
    name: str,
    is_identity: bool = False,
    is_computed: bool = False,
    type_name: str = "nvarchar",
) -> TableColumn:
    return TableColumn(
        name=name,
        column_id=1,
        is_identity=is_identity,
        is_computed=is_computed,
        generated_always_type=0,
        type_name=type_name,
        is_primary_key=False,
    )


if __name__ == "__main__":
    unittest.main()
