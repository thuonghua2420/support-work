from __future__ import annotations

import unittest

from autocompare_tool.db_roundtrip import TableColumn, _reorder_csv_by_db_columns
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


def _column(name: str, is_identity: bool = False, is_computed: bool = False) -> TableColumn:
    return TableColumn(
        name=name,
        column_id=1,
        is_identity=is_identity,
        is_computed=is_computed,
        generated_always_type=0,
        type_name="nvarchar",
        is_primary_key=False,
    )


if __name__ == "__main__":
    unittest.main()
