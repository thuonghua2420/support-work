from __future__ import annotations

import unittest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from autocompare_tool.app_config import DatabaseWorkspaceConfig
from autocompare_tool.database_io import DatabaseColumn, DatabaseConnectionSettings, SqlServerAdapter, TableMetadata
from autocompare_tool.sql_database_workspace import (
    SqlDatabaseWorkspaceManager,
    _Workspace,
    _decorate_column_usage,
    _diagnostic_source_sql,
    _display_value,
    _group_source_relations,
    _init_spool,
    _merged_source_relation,
    _read_spool_rows,
    _spool_cursor_unique,
    is_read_statement,
)
from autocompare_tool.sql_tools import analyze_sql, parse_sql_expressions


class SqlDatabaseWorkspaceTests(unittest.TestCase):
    def test_statement_classification_gates_write_sql(self) -> None:
        select_expr = parse_sql_expressions("SELECT id FROM dbo.customers", "tsql")[0]
        update_expr = parse_sql_expressions("UPDATE dbo.customers SET name = 'A'", "tsql")[0]

        self.assertTrue(is_read_statement(select_expr))
        self.assertFalse(is_read_statement(update_expr))

    def test_execution_inspection_distinguishes_select_from_cud(self) -> None:
        read_plan = SqlDatabaseWorkspaceManager._prepare_execution(
            "SELECT id FROM dbo.customers", "tsql", "all"
        )
        write_plan = SqlDatabaseWorkspaceManager._prepare_execution(
            "UPDATE dbo.customers SET name = 'A'", "tsql", "current"
        )

        self.assertFalse(read_plan.write_required)
        self.assertEqual("", read_plan.parse_error)
        self.assertTrue(write_plan.write_required)
        self.assertEqual(1, len(write_plan.statement_sqls))

    def test_execute_read_only_returns_empty_parse_error(self) -> None:
        class Cursor:
            description = None
            rowcount = -1

        class Connection:
            def cursor(self):
                return Cursor()

            def rollback(self):
                return None

            def close(self):
                return None

        class Adapter:
            def connect(self, _settings):
                return Connection()

            def execute(self, _cursor, _sql):
                return None

        config = DatabaseWorkspaceConfig(
            page_size=20,
            max_page_size=100,
            query_timeout_seconds=30,
            write_mode_timeout_minutes=5,
            export_batch_size=50,
            workspace_spool_limit_mb=10,
        )
        manager = SqlDatabaseWorkspaceManager(config)
        self.addCleanup(manager.close)
        settings = DatabaseConnectionSettings(
            database_type="SQL Server",
            host="localhost",
            database="sample",
            schema="dbo",
            trusted_connection=True,
            driver="ODBC Driver 17 for SQL Server",
        )

        with patch("autocompare_tool.sql_database_workspace.get_adapter", return_value=Adapter()):
            result = manager.execute("SELECT 1", settings)

        self.assertEqual("", result["parse_error"])
        self.assertEqual("read_only", result["transaction_status"])

    def test_execute_all_continues_after_one_statement_fails(self) -> None:
        executed: list[str] = []

        class Cursor:
            description = None
            rowcount = -1

        class Connection:
            def cursor(self):
                return Cursor()

            def rollback(self):
                return None

            def close(self):
                return None

        class Adapter:
            def connect(self, _settings):
                return Connection()

            def execute(self, _cursor, sql):
                executed.append(sql)
                if len(executed) == 10:
                    raise RuntimeError("statement ten failed")

        config = DatabaseWorkspaceConfig(
            page_size=20,
            max_page_size=100,
            query_timeout_seconds=30,
            write_mode_timeout_minutes=5,
            export_batch_size=50,
            workspace_spool_limit_mb=10,
        )
        manager = SqlDatabaseWorkspaceManager(config)
        self.addCleanup(manager.close)
        settings = DatabaseConnectionSettings(
            database_type="SQL Server",
            host="localhost",
            database="sample",
            schema="dbo",
            trusted_connection=True,
            driver="ODBC Driver 17 for SQL Server",
        )
        sql = ";".join(f"SELECT {index}" for index in range(1, 13))

        with patch("autocompare_tool.sql_database_workspace.get_adapter", return_value=Adapter()):
            result = manager.execute(sql, settings)

        self.assertEqual(12, len(executed))
        self.assertEqual(12, len(result["statements"]))
        self.assertIn("statement ten failed", result["statements"][9]["error"])
        self.assertEqual(12, result["statements"][-1]["statement_index"])

    def test_source_relations_group_aliases_for_the_same_table(self) -> None:
        first = _relation("r1", "Customer", "c", [_column("CustomerId")])
        second = _relation("r2", "Customer", "parent", [_column("CustomerId")])
        first.update({"source_type": "TABLE", "lineage_status": "exact", "source_sql": "SELECT 1"})
        second.update({"source_type": "TABLE", "lineage_status": "exact", "source_sql": "SELECT 2"})

        groups = _group_source_relations([first, second])
        merged = _merged_source_relation(first, groups[0])

        self.assertEqual(1, len(groups))
        self.assertEqual(["c", "parent"], merged["aliases"])
        self.assertEqual("c, parent", merged["alias"])
        self.assertEqual("SELECT 1;\n\nSELECT 2", merged["source_sql"])

    def test_grouped_source_rows_are_unique_by_primary_key(self) -> None:
        class Cursor:
            def __init__(self, rows):
                self.rows = list(rows)

            def fetchmany(self, _size):
                rows, self.rows = self.rows, []
                return rows

        settings = DatabaseConnectionSettings(
            database_type="SQL Server",
            host="localhost",
            database="sample",
            schema="dbo",
            trusted_connection=True,
            driver="ODBC Driver 17 for SQL Server",
        )
        columns = [
            DatabaseColumn(name="CustomerId", ordinal=1, data_type="int", is_primary_key=True),
            DatabaseColumn(name="Name", ordinal=2, data_type="nvarchar"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = _Workspace(
                workspace_id="test",
                root_path=root,
                sqlite_path=root / "spool.sqlite3",
                fingerprint="test",
                dialect="tsql",
                created_at=time.time(),
                expires_at=time.time() + 60,
                settings=settings,
            )
            _init_spool(workspace.sqlite_path)
            seen: set[str] = set()
            _spool_cursor_unique(workspace, "source-r1", Cursor([(1, "A"), (2, "B")]), columns, 50, 10, seen)
            count = _spool_cursor_unique(workspace, "source-r1", Cursor([(2, "B changed"), (3, "C")]), columns, 50, 10, seen)
            rows = _read_spool_rows(workspace.sqlite_path, "source-r1", 0, 10)

        self.assertEqual(3, count)
        self.assertEqual(3, len(rows))

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
        self.assertEqual(
            [
                "dbo.A AS a, col1, index #1",
                "dbo.B AS b, col6, index #1",
                "dbo.C AS c, col3, index #1",
            ],
            a_col["join_tooltip"].splitlines(),
        )
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
        self.assertEqual("exact row-participation primary-key trace", strategy)
        self.assertIn("__ac_pk_1", trace_sql)
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

    def test_source_data_traces_grouped_rows(self) -> None:
        sql = "SELECT o.status, COUNT(*) FROM dbo.Office o GROUP BY o.status"
        expression = parse_sql_expressions(sql, "tsql")[0]
        analysis = analyze_sql(sql, "tsql")
        table_ref = next(item for item in analysis.tables if item.alias == "o")
        metadata = TableMetadata(
            schema="dbo",
            name="Office",
            columns=[DatabaseColumn(name="OFFICECD", ordinal=1, data_type="int", is_primary_key=True),
                     DatabaseColumn(name="status", ordinal=2, data_type="nvarchar")],
        )

        source_sql, reason, trace_sql, strategy = _diagnostic_source_sql(
            expression,
            table_ref,
            metadata,
            SqlServerAdapter(),
            "tsql",
        )

        self.assertTrue(source_sql, reason)
        self.assertIn("GROUP BY", trace_sql)
        self.assertEqual("exact row-participation primary-key trace", strategy)
        self.assertEqual("", reason)

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
