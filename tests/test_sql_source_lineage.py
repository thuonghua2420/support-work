import sqlite3
import unittest
from collections import Counter
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from sqlglot import parse_one

from autocompare_tool.dbeaver_csv import read_dbeaver_csv
from autocompare_tool.database_io import DatabaseColumn, SqlServerAdapter, TableMetadata
from autocompare_tool.sql_database_workspace import SqlDatabaseWorkspaceManager, _build_relations, _diagnostic_source_sql
from autocompare_tool.sql_tools import analyze_sql, parse_sql_expressions


class ProjectionLineageTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE A (id INTEGER PRIMARY KEY, value INTEGER);
            CREATE TABLE B (id INTEGER PRIMARY KEY, aid INTEGER);
            INSERT INTO A VALUES (1,10),(2,20),(3,20),(4,40);
            INSERT INTO B VALUES (11,1),(12,2),(13,3),(14,9);
        """)

    def sources(self, sql):
        statement = parse_sql_expressions(sql, "tsql")[0]
        analysis = analyze_sql(sql, "tsql")
        selected = {}
        for ref in analysis.tables:
            if ref.source_type != "TABLE":
                continue
            names = ["id", "value" if ref.name == "A" else "aid"]
            metadata = TableMetadata(schema="main", name=ref.name, columns=[
                DatabaseColumn(name=name, ordinal=index, data_type="int", is_primary_key=index == 1)
                for index, name in enumerate(names, 1)
            ])
            source_sql, reason, trace, _strategy = _diagnostic_source_sql(
                statement, ref, metadata, SqlServerAdapter(), "tsql",
            )
            self.assertTrue(source_sql, reason)
            self.assertTrue(trace)
            executable = parse_one(source_sql, read="tsql").sql(dialect="sqlite")
            rows = self.db.execute(executable).fetchall()
            selected.setdefault(ref.name, set()).update(rows)
        return selected

    def assert_replays(self, sql, expected):
        executable = sql
        original = Counter(self.db.execute(executable).fetchall())
        selected = self.sources(sql)
        self.assertEqual(selected, expected)
        with sqlite3.connect(":memory:") as replay:
            replay.executescript("CREATE TABLE A (id INTEGER PRIMARY KEY, value INTEGER); CREATE TABLE B (id INTEGER PRIMARY KEY, aid INTEGER);")
            for table, rows in selected.items():
                replay.executemany(f"INSERT INTO {table} VALUES (?,?)", rows)
            self.assertEqual(Counter(replay.execute(executable).fetchall()), original)

    def test_nested_cte_computed_projection_and_outer_join_predicates(self):
        self.assert_replays("""
            WITH x AS (SELECT a.id AS code, a.value * 2 AS amount FROM A a),
                 y AS (SELECT code, amount + 1 AS total FROM x)
            SELECT y.total, b.id FROM y JOIN B b ON y.code=b.aid
            WHERE y.total > 30 AND b.id=12
        """, {"A": {(2,20)}, "B": {(12,2)}})

    def test_derived_table_key_not_in_original_projection(self):
        self.assert_replays("SELECT q.amount FROM (SELECT a.value+1 AS amount FROM A a) q WHERE q.amount=21",
                            {"A": {(2,20),(3,20)}})

    def test_cte_reused_in_self_join_collects_both_branches(self):
        self.assert_replays("WITH x AS (SELECT id,value FROM A) SELECT p.value,q.value FROM x p JOIN x q ON p.id+1=q.id WHERE p.id=1",
                            {"A": {(1,10),(2,20)}})

    def test_cte_column_list_and_distinct_projection(self):
        self.assert_replays("WITH x(amount) AS (SELECT DISTINCT value FROM A) SELECT amount FROM x WHERE amount=20",
                            {"A": {(2,20),(3,20)}})

    def test_nested_star_and_alias_shadowing(self):
        self.assert_replays("SELECT a.value FROM (SELECT * FROM (SELECT * FROM A a) a) a WHERE a.id=2",
                            {"A": {(2,20)}})

    def test_left_join_preserves_unmatched_row(self):
        self.assert_replays("WITH x AS (SELECT id,value FROM A) SELECT x.value,b.id FROM x LEFT JOIN B b ON b.aid=x.id WHERE x.id=4",
                            {"A": {(4,40)}, "B": set()})

    def test_nested_aggregate_is_not_mislabeled_exact(self):
        sql = "WITH x AS (SELECT SUM(value) AS total FROM A) SELECT total FROM x"
        ref = next(ref for ref in analyze_sql(sql, "tsql").tables if ref.name == "A")
        metadata = TableMetadata(schema="", name="A", columns=[DatabaseColumn(name="id", ordinal=1, data_type="int", is_primary_key=True)])
        source, reason, _trace, _strategy = _diagnostic_source_sql(parse_sql_expressions(sql, "tsql")[0], ref, metadata, SqlServerAdapter(), "tsql")
        self.assertFalse(source)
        self.assertIn("Aggregate", reason)

    def test_complex_queries_capture_every_dependency_and_replay(self):
        class Adapter(SqlServerAdapter):
            def get_relation(self, connection, settings, name, schema):
                columns = ["id", "value" if name == "A" else "aid"]
                return TableMetadata(schema="main", name=name, columns=[
                    DatabaseColumn(name=column, ordinal=index, data_type="int", is_primary_key=index == 1)
                    for index, column in enumerate(columns, 1)
                ])

        queries = [
            "WITH x AS (SELECT value,COUNT(*) n FROM A GROUP BY value HAVING COUNT(*)>1) SELECT * FROM x",
            "SELECT a.id FROM A a WHERE NOT EXISTS(SELECT 1 FROM B b WHERE b.aid=a.id)",
            "SELECT a.id,(SELECT COUNT(*) FROM B b WHERE b.aid=a.id) FROM A a",
            "WITH x AS (SELECT id,ROW_NUMBER() OVER(ORDER BY value,id) rn FROM A) SELECT id FROM x WHERE rn=2",
            "SELECT id FROM A UNION SELECT aid FROM B",
            "WITH RECURSIVE x(id) AS (SELECT id FROM A WHERE id=1 UNION ALL SELECT a.id FROM A a JOIN x ON a.id=x.id+1) SELECT id FROM x",
        ]
        for sql in queries:
            with self.subTest(sql=sql):
                expressions = parse_sql_expressions(sql, "sqlite")
                relations = _build_relations(SimpleNamespace(settings=None), Adapter(), None,
                                             expressions, analyze_sql(sql, "sqlite"), "sqlite")
                physical = [relation for relation in relations if relation["source_type"] == "TABLE"]
                selected = {}
                for relation in physical:
                    self.assertEqual(relation["lineage_status"], "snapshot")
                    self.assertFalse(relation["updateable"])
                    self.assertFalse(any(column["editable"] for column in relation["columns"]))
                    selected[relation["name"]] = self.db.execute(relation["source_sql"]).fetchall()
                with sqlite3.connect(":memory:") as replay:
                    replay.executescript("CREATE TABLE A(id INTEGER PRIMARY KEY,value INTEGER); CREATE TABLE B(id INTEGER PRIMARY KEY,aid INTEGER);")
                    for name, rows in selected.items():
                        replay.executemany(f"INSERT INTO {name} VALUES (?,?)", rows)
                    self.assertEqual(Counter(self.db.execute(sql).fetchall()), Counter(replay.execute(sql).fetchall()))

    def test_snapshot_is_paged_and_exported_without_negative_rows(self):
        from autocompare_tool.app_config import DatabaseWorkspaceConfig
        config = DatabaseWorkspaceConfig(page_size=2, max_page_size=100, export_batch_size=2,
                                         query_timeout_seconds=30, workspace_spool_limit_mb=10,
                                         write_mode_timeout_minutes=5)
        manager = SqlDatabaseWorkspaceManager(config)
        self.addCleanup(manager.close)
        workspace = manager._create_workspace(None, "test", "sqlite")
        metadata = TableMetadata(schema="main", name="A", columns=[
            DatabaseColumn(name="id", ordinal=1, data_type="int", is_primary_key=True),
            DatabaseColumn(name="value", ordinal=2, data_type="int"),
        ])
        adapter = SqlServerAdapter()
        sql = "SELECT value,COUNT(*) FROM A GROUP BY value"
        with patch.object(adapter, "get_relation", return_value=metadata):
            manager._analyze_and_spool_sources(workspace, adapter, self.db, sql,
                                              parse_sql_expressions(sql, "sqlite"), "sqlite")
        source = workspace.sources[0]
        self.assertEqual(source["lineage_status"], "snapshot", source)
        self.assertEqual(source["row_count"], 4)
        page = manager.get_page(workspace.workspace_id, source["item_id"], page=2)
        self.assertEqual(len(page["rows"]), 2)
        with patch("autocompare_tool.sql_database_workspace._find_negative_row") as negative:
            exported = manager._export_one_source(workspace, source, workspace.relations[source["relation_id"]],
                                                  self.db, adapter, workspace.root_path, lambda _: None)
        negative.assert_not_called()
        self.assertEqual(exported["negative_record_count"], 0)
        self.assertEqual(read_dbeaver_csv(Path(exported["path"])).rows,
                         [["1","10"],["2","20"],["3","20"],["4","40"]])


if __name__ == "__main__":
    unittest.main()
