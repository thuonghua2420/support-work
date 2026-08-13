from __future__ import annotations

import unittest

from autocompare_tool.database_io import DatabaseColumn, SqlServerAdapter, TableMetadata
from autocompare_tool.sql_database_workspace import _decorate_column_usage, _diagnostic_source_sql, _display_value, is_read_statement
from autocompare_tool.sql_tools import analyze_sql, parse_sql_expressions


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
        self.assertIn("Column hiện tại: dbo.A AS a.col1 (index #1)", a_col["join_tooltip"])
        self.assertIn("dbo.B AS b.col6 (index #1)", a_col["join_tooltip"])
        self.assertIn("dbo.C AS c.col3 (index #1)", a_col["join_tooltip"])
        self.assertIn("Biểu thức JOIN:", a_col["join_tooltip"])
        self.assertEqual("WHERE", status_col["usage"])

    def test_source_data_uses_matched_primary_key_trace(self) -> None:
        sql = """
            SELECT o.OFFICENM
            FROM dbo.Office o
            JOIN dbo.NmInfo n ON o.OFFICECD = n.OFFICECD
            WHERE EXISTS (
                SELECT 1
                FROM dbo.OfficePermit p
                WHERE p.OFFICECD = o.OFFICECD
            )
        """
        expression = parse_sql_expressions(sql, "tsql")[0]
        analysis = analyze_sql(sql, "tsql")
        table_ref = next(item for item in analysis.tables if item.alias == "o")
        metadata = TableMetadata(
            schema="dbo",
            name="Office",
            columns=[
                DatabaseColumn(name="OFFICECD", ordinal=1, data_type="int", is_primary_key=True),
                DatabaseColumn(name="OFFICENM", ordinal=2, data_type="nvarchar"),
            ],
        )

        source_sql, reason, trace_sql, strategy = _diagnostic_source_sql(
            expression,
            table_ref,
            metadata,
            SqlServerAdapter(),
            "tsql",
        )

        self.assertEqual("", reason)
        self.assertEqual("exact matched primary-key trace", strategy)
        self.assertIn("__ac_pk_1", trace_sql)
        self.assertIn("DISTINCT", trace_sql.upper())
        self.assertIn("EXISTS", trace_sql.upper())
        self.assertIn("INNER JOIN", source_sql.upper())
        self.assertIn("ORDER BY", source_sql.upper())

    def test_source_data_allows_cte_reference_projection(self) -> None:
        sql = "WITH x AS (SELECT id FROM dbo.A) SELECT * FROM x"
        expression = parse_sql_expressions(sql, "tsql")[0]
        analysis = analyze_sql(sql, "tsql")
        table_ref = next(item for item in analysis.tables if item.source_type == "CTE_REFERENCE")
        metadata = TableMetadata(schema="", name="x", columns=[], relation_type="CTE")

        source_sql, reason, trace_sql, strategy = _diagnostic_source_sql(
            expression,
            table_ref,
            metadata,
            SqlServerAdapter(),
            "tsql",
        )

        self.assertEqual("", reason)
        self.assertEqual("", trace_sql)
        self.assertEqual("exact source projection", strategy)
        self.assertIn("SELECT DISTINCT", source_sql.upper())

    def test_source_data_rejects_base_table_without_metadata_columns(self) -> None:
        sql = "SELECT * FROM dbo.A a"
        expression = parse_sql_expressions(sql, "tsql")[0]
        analysis = analyze_sql(sql, "tsql")
        table_ref = next(item for item in analysis.tables if item.alias == "a")
        metadata = TableMetadata(schema="dbo", name="A", columns=[])

        source_sql, reason, trace_sql, strategy = _diagnostic_source_sql(
            expression,
            table_ref,
            metadata,
            SqlServerAdapter(),
            "tsql",
        )

        self.assertEqual("", source_sql)
        self.assertEqual("", trace_sql)
        self.assertEqual("", strategy)
        self.assertIn("metadata", reason.lower())

    def test_source_data_rejects_grouped_trace_until_group_lineage_exists(self) -> None:
        sql = "SELECT o.status, COUNT(*) FROM dbo.Office o GROUP BY o.status"
        expression = parse_sql_expressions(sql, "tsql")[0]
        analysis = analyze_sql(sql, "tsql")
        table_ref = next(item for item in analysis.tables if item.alias == "o")
        metadata = TableMetadata(
            schema="dbo",
            name="Office",
            columns=[DatabaseColumn(name="OFFICECD", ordinal=1, data_type="int", is_primary_key=True)],
        )

        source_sql, reason, trace_sql, strategy = _diagnostic_source_sql(
            expression,
            table_ref,
            metadata,
            SqlServerAdapter(),
            "tsql",
        )

        self.assertEqual("", source_sql)
        self.assertEqual("", trace_sql)
        self.assertEqual("", strategy)
        self.assertIn("group", reason.lower())

    def test_database_grid_displays_null_marker_but_empty_as_blank(self) -> None:
        column = {"name": "name", "index": 1, "data_type": "nvarchar", "nullable": True}

        self.assertEqual("[NULL]", _display_value(None, column))
        self.assertEqual("", _display_value("", column))


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
