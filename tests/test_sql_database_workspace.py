from __future__ import annotations

import unittest

from autocompare_tool.database_io import DatabaseColumn, TableMetadata
from autocompare_tool.sql_database_workspace import _decorate_column_usage, is_read_statement
from autocompare_tool.sql_tools import parse_sql_expressions


class SqlDatabaseWorkspaceTests(unittest.TestCase):
    def test_statement_classification_gates_write_sql(self) -> None:
        select_expr = parse_sql_expressions("SELECT id FROM dbo.customers", "tsql")[0]
        update_expr = parse_sql_expressions("UPDATE dbo.customers SET name = 'A'", "tsql")[0]

        self.assertTrue(is_read_statement(select_expr))
        self.assertFalse(is_read_statement(update_expr))

    def test_join_group_is_transitive_and_takes_color_priority(self) -> None:
        expression = parse_sql_expressions(
            """
            SELECT a.col1, b.col6, c.col3
            FROM dbo.A a
            JOIN dbo.B b ON a.col1 = b.col6
            JOIN dbo.C c ON a.col1 = c.col3
            WHERE a.status = 'Y'
            """,
            "tsql",
        )[0]
        relations = [
            _relation("ra", "A", "a", [_column("col1"), _column("status")]),
            _relation("rb", "B", "b", [_column("col6")]),
            _relation("rc", "C", "c", [_column("col3")]),
        ]

        _decorate_column_usage([expression], relations)

        a_col = _column_info(relations[0], "col1")
        b_col = _column_info(relations[1], "col6")
        c_col = _column_info(relations[2], "col3")
        status_col = _column_info(relations[0], "status")

        self.assertEqual("JOIN", a_col["usage"])
        self.assertEqual(a_col["join_group"], b_col["join_group"])
        self.assertEqual(a_col["join_group"], c_col["join_group"])
        self.assertEqual(a_col["color"], b_col["color"])
        self.assertEqual(a_col["color"], c_col["color"])
        self.assertEqual("WHERE", status_col["usage"])


def _relation(
    relation_id: str,
    name: str,
    alias: str,
    columns: list[DatabaseColumn],
) -> dict[str, object]:
    metadata = TableMetadata(schema="dbo", name=name, columns=columns)
    return {
        "relation_id": relation_id,
        "statement_index": 1,
        "scope_id": "S1.Q1",
        "qualified_name": f"dbo.{name}",
        "name": name,
        "alias": alias,
        "columns": [
            {
                "index": column.ordinal,
                "name": column.name,
                "data_type": column.data_type,
                "is_primary_key": column.is_primary_key,
                "editable": False,
            }
            for column in metadata.columns
        ],
    }


def _column(name: str) -> DatabaseColumn:
    return DatabaseColumn(name=name, ordinal=1, data_type="int")


def _column_info(relation: dict[str, object], name: str) -> dict[str, object]:
    for column in relation["columns"]:
        if column["name"] == name:
            return column
    raise AssertionError(f"missing column {name}")


if __name__ == "__main__":
    unittest.main()
