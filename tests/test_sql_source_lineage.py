import sqlite3
import unittest
from collections import Counter
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from sqlglot import exp, parse_one

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
                statement, ref, metadata, SqlServerAdapter(), "tsql", self.metadata(),
            )
            self.assertTrue(source_sql, reason)
            self.assertTrue(trace)
            executable = parse_one(source_sql, read="tsql").sql(dialect="sqlite")
            rows = self.db.execute(executable).fetchall()
            selected.setdefault(ref.name, set()).update(rows)
        return selected

    def metadata(self):
        return [TableMetadata(schema="main", name=table, columns=[
            DatabaseColumn(name="id", ordinal=1, data_type="int", is_primary_key=True),
            DatabaseColumn(name=column, ordinal=2, data_type="int"),
        ]) for table, column in [("A", "value"), ("B", "aid")]]

    def assert_replays(self, sql, expected):
        parsed = parse_one(sql, read="tsql")
        has_limit = any(query.args.get("limit") for query in parsed.find_all(exp.Select))
        executable = parsed.sql(dialect="sqlite") if has_limit else sql
        original = Counter(self.db.execute(executable).fetchall())
        selected = self.sources(sql)
        self.assertEqual(selected, expected)
        with sqlite3.connect(":memory:") as replay:
            self.addCleanup(replay.close)
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

    def test_grouped_cte_keeps_only_selected_group_members(self):
        self.assert_replays("""
            WITH x AS (SELECT value, COUNT(*) AS n FROM A GROUP BY value HAVING COUNT(*)>1),
                 y AS (SELECT value,n FROM x WHERE n=2)
            SELECT y.n,b.id FROM y JOIN B b ON b.aid=y.value/10 WHERE b.id=12
        """, {"A": {(2,20),(3,20)}, "B": {(12,2)}})

    def test_distinct_cte_does_not_multiply_outer_aggregate(self):
        self.assert_replays("WITH x AS (SELECT DISTINCT value FROM A) SELECT COUNT(*) AS n FROM x WHERE value=20",
                            {"A": {(2,20),(3,20)}})

    def test_nested_correlated_subqueries_follow_selected_outer_rows(self):
        self.assert_replays("""
            SELECT a.id FROM A a WHERE a.id=2 AND EXISTS (
              SELECT 1 FROM B b WHERE b.aid=a.id AND EXISTS (
                SELECT 1 FROM A c WHERE c.id=b.aid AND c.value=20))
        """, {"A": {(2,20)}, "B": {(12,2)}})

    def test_scalar_aggregate_uses_only_correlated_records(self):
        self.assert_replays("SELECT a.id,(SELECT COUNT(*) FROM B b WHERE b.aid=a.id) AS n FROM A a WHERE a.id=2",
                            {"A": {(2,20)}, "B": {(12,2)}})

    def test_in_subquery_uses_matching_values_only(self):
        self.assert_replays("SELECT a.id FROM A a WHERE a.id=2 AND a.id IN (SELECT b.aid FROM B b)",
                            {"A": {(2,20)}, "B": {(12,2)}})

    def test_top_retains_order_and_only_selected_record(self):
        self.assert_replays("WITH x AS (SELECT TOP 2 id,value FROM A ORDER BY id DESC) SELECT id FROM x WHERE value=20",
                            {"A": {(3,20)}})

    def test_union_outer_filter_and_reused_cte(self):
        self.assert_replays("""
            WITH x AS (SELECT id AS code FROM A UNION SELECT aid AS code FROM B)
            SELECT p.code,q.code FROM x p JOIN x q ON p.code+1=q.code WHERE p.code=1
        """, {"A": {(1,10),(2,20)}, "B": {(11,1),(12,2)}})

    def test_intersect_and_except(self):
        for operator, expected in [
            ("INTERSECT", {"A": {(2,20)}, "B": {(12,2)}}),
            ("EXCEPT", {"A": {(4,40)}, "B": set()}),
        ]:
            with self.subTest(operator=operator):
                value = 2 if operator == "INTERSECT" else 4
                self.assert_replays(f"SELECT id FROM (SELECT id FROM A {operator} SELECT aid FROM B) x WHERE id={value}", expected)

    def test_window_dependencies_stay_in_selected_partition(self):
        self.assert_replays("""
            WITH x AS (SELECT id,value,ROW_NUMBER() OVER(PARTITION BY value ORDER BY id) AS rn FROM A)
            SELECT id FROM x WHERE value=20 AND rn=2
        """, {"A": {(2,20),(3,20)}})

    def test_empty_result_produces_empty_sources(self):
        self.assert_replays("WITH x AS (SELECT value,COUNT(*) AS n FROM A GROUP BY value) SELECT * FROM x WHERE n>10",
                            {"A": set()})

    def test_grouped_join_preserves_all_members_and_excludes_other_groups(self):
        self.db.execute("INSERT INTO B VALUES (15,2),(16,4)")
        self.assert_replays("""
            WITH x AS (SELECT a.value,COUNT(*) AS n FROM A a JOIN B b ON b.aid=a.id GROUP BY a.value)
            SELECT * FROM x WHERE value=20 AND n=3
        """, {"A": {(2,20),(3,20)}, "B": {(12,2),(13,3),(15,2)}})

    def test_null_group_uses_null_safe_membership(self):
        self.db.execute("INSERT INTO A VALUES (5,NULL),(6,NULL)")
        self.assert_replays("WITH x AS (SELECT value,COUNT(*) AS n FROM A GROUP BY value) SELECT n FROM x WHERE value IS NULL",
                            {"A": {(5,None),(6,None)}})

    def test_nested_with_and_explicit_grouped_cte_columns(self):
        self.assert_replays("""
            WITH x(amount,n) AS (SELECT value,COUNT(*) FROM A GROUP BY value)
            SELECT q.n FROM (WITH y AS (SELECT * FROM x) SELECT * FROM y WHERE amount=20) q
        """, {"A": {(2,20),(3,20)}})

    def test_grouped_left_join_without_match(self):
        self.assert_replays("""
            WITH x AS (SELECT aid,COUNT(*) AS n FROM B GROUP BY aid)
            SELECT a.id,x.n FROM A a LEFT JOIN x ON a.id=x.aid WHERE a.id=4
        """, {"A": {(4,40)}, "B": set()})

    def test_top_distinct_orders_after_deduplication(self):
        self.assert_replays("SELECT DISTINCT TOP 1 value FROM A WHERE value<40 ORDER BY value DESC",
                            {"A": {(2,20),(3,20)}})

    def test_scalar_top_keeps_only_selected_child(self):
        self.db.execute("INSERT INTO B VALUES (15,2)")
        self.assert_replays("SELECT a.id,(SELECT TOP 1 b.id FROM B b WHERE b.aid=a.id ORDER BY b.id DESC) AS bid FROM A a WHERE a.id=2",
                            {"A": {(2,20)}, "B": {(15,2)}})

    def test_ranking_does_not_collect_later_partition_rows(self):
        self.assert_replays("""
            WITH x AS (SELECT id,value,ROW_NUMBER() OVER(PARTITION BY value ORDER BY id) AS rn FROM A)
            SELECT id FROM x WHERE value=20 AND rn=1
        """, {"A": {(2,20)}})

    def test_composite_key_is_matched_as_a_tuple(self):
        self.db.executescript("""
            CREATE TABLE C(tenant INTEGER,code INTEGER,amount INTEGER,PRIMARY KEY(tenant,code));
            INSERT INTO C VALUES (1,1,10),(1,2,20),(2,1,30),(2,2,40);
        """)
        sql = "WITH x AS (SELECT tenant,SUM(amount) AS total FROM C GROUP BY tenant) SELECT * FROM x WHERE total=30"
        metadata = TableMetadata(schema="main", name="C", columns=[
            DatabaseColumn(name=name, ordinal=index, data_type="int", is_primary_key=index<3)
            for index, name in enumerate(["tenant", "code", "amount"], 1)
        ])
        ref = next(ref for ref in analyze_sql(sql, "tsql").tables if ref.name == "C")
        source, reason, _, _ = _diagnostic_source_sql(parse_one(sql, read="tsql"), ref, metadata, SqlServerAdapter(), "tsql")
        self.assertTrue(source, reason)
        self.assertEqual(self.db.execute(parse_one(source, read="tsql").sql(dialect="sqlite")).fetchall(),
                         [(1,1,10),(1,2,20)])

    def test_unused_scalar_projection_does_not_capture_records(self):
        self.assert_replays("""
            SELECT x.id FROM (SELECT a.id,(SELECT COUNT(*) FROM B) AS unused FROM A a) x WHERE x.id=2
        """, {"A": {(2,20)}, "B": set()})

    def test_case_only_traces_the_selected_branch(self):
        self.assert_replays("""
            SELECT a.id,CASE WHEN a.id=1 THEN (SELECT MAX(b.id) FROM B b WHERE b.aid=a.id)
                            ELSE 0 END AS bid FROM A a WHERE a.id=2
        """, {"A": {(2,20)}, "B": set()})

    def test_complex_queries_capture_only_participating_dependencies_and_replay(self):
        class Adapter(SqlServerAdapter):
            def get_relation(self, connection, settings, name, schema):
                columns = ["id", "value" if name == "A" else "aid"]
                return TableMetadata(schema="main", name=name, columns=[
                    DatabaseColumn(name=column, ordinal=index, data_type="int", is_primary_key=index == 1)
                    for index, column in enumerate(columns, 1)
                ])

        queries = [
            ("WITH x AS (SELECT value,COUNT(*) n FROM A GROUP BY value HAVING COUNT(*)>1) SELECT * FROM x", {"A": [(2,20),(3,20)]}),
            ("SELECT a.id FROM A a WHERE NOT EXISTS(SELECT 1 FROM B b WHERE b.aid=a.id)", {"A": [(4,40)], "B": []}),
            ("SELECT a.id,(SELECT COUNT(*) FROM B b WHERE b.aid=a.id) FROM A a WHERE a.id=2", {"A": [(2,20)], "B": [(12,2)]}),
            ("WITH x AS (SELECT id,ROW_NUMBER() OVER(PARTITION BY value ORDER BY id) rn FROM A WHERE value=20) SELECT id FROM x WHERE rn=2", {"A": [(2,20),(3,20)]}),
            ("SELECT id FROM A WHERE id=2 UNION SELECT aid FROM B WHERE aid=2", {"A": [(2,20)], "B": [(12,2)]}),
        ]
        for sql, expected in queries:
            with self.subTest(sql=sql):
                expressions = parse_sql_expressions(sql, "sqlite")
                relations = _build_relations(SimpleNamespace(settings=None), Adapter(), None,
                                             expressions, analyze_sql(sql, "sqlite"), "sqlite")
                physical = [relation for relation in relations if relation["source_type"] == "TABLE"]
                selected = {}
                for relation in physical:
                    self.assertEqual(relation["lineage_status"], "exact", relation["unsupported_reason"])
                    selected[relation["name"]] = self.db.execute(relation["source_sql"]).fetchall()
                self.assertEqual(selected, expected)
                with sqlite3.connect(":memory:") as replay:
                    self.addCleanup(replay.close)
                    replay.executescript("CREATE TABLE A(id INTEGER PRIMARY KEY,value INTEGER); CREATE TABLE B(id INTEGER PRIMARY KEY,aid INTEGER);")
                    for name, rows in selected.items():
                        replay.executemany(f"INSERT INTO {name} VALUES (?,?)", rows)
                    self.assertEqual(Counter(self.db.execute(sql).fetchall()), Counter(replay.execute(sql).fetchall()))

    def test_recursive_query_traces_only_the_selected_path(self):
        self.assert_replays("WITH x(id) AS (SELECT id FROM A WHERE id=1 UNION ALL SELECT a.id FROM A a JOIN x ON a.id=x.id+1) SELECT id FROM x WHERE id=3",
                            {"A": {(1,10),(2,20),(3,20)}})

    def test_tsql_implicit_recursive_reference_is_not_a_physical_table(self):
        sql = "WITH x AS (SELECT id FROM A WHERE id=1 UNION ALL SELECT a.id FROM A a JOIN x ON a.id=x.id+1) SELECT id FROM x"
        references = [ref for ref in analyze_sql(sql, "tsql").tables if ref.name == "x"]
        self.assertTrue(references)
        self.assertTrue(all(ref.source_type == "CTE_REFERENCE" for ref in references))

    def test_recursive_query_hint_remains_at_statement_level(self):
        sql = "WITH x AS (SELECT id FROM A WHERE id=1 UNION ALL SELECT a.id FROM A a JOIN x ON a.id=x.id+1) SELECT id FROM x WHERE id=3 OPTION(MAXRECURSION 0)"
        expression = parse_sql_expressions(sql, "tsql")[0]
        for ref in analyze_sql(sql, "tsql").tables:
            if ref.source_type != "TABLE":
                continue
            source, reason, _, _ = _diagnostic_source_sql(expression, ref, self.metadata()[0], SqlServerAdapter(), "tsql", self.metadata())
            self.assertTrue(source, reason)
            generated = parse_one(source, read="tsql")
            self.assertTrue(generated.args.get("options"))
            self.assertEqual(sum(bool(query.args.get("options")) for query in generated.find_all(exp.Query)), 1)

    def test_grouped_scalar_subquery_alias_shadowing(self):
        self.assert_replays("SELECT a.value,(SELECT COUNT(*) FROM A a WHERE a.value=10) AS n FROM A a GROUP BY a.value HAVING a.value=20",
                            {"A": {(1,10),(2,20),(3,20)}})

    def test_missing_key_does_not_expand_other_sources_to_all_rows(self):
        metadata = self.metadata()
        metadata[1] = TableMetadata(schema="main", name="B", columns=[
            DatabaseColumn(name="id", ordinal=1, data_type="int"),
            DatabaseColumn(name="aid", ordinal=2, data_type="int"),
        ])
        adapter = SqlServerAdapter()
        sql = "SELECT a.id FROM A a JOIN B b ON a.id=b.aid WHERE a.id=2"
        with patch.object(adapter, "get_relation", side_effect=metadata):
            relations = _build_relations(SimpleNamespace(settings=None), adapter, None,
                                         parse_sql_expressions(sql, "tsql"), analyze_sql(sql, "tsql"), "tsql")
        self.assertEqual(relations[0]["lineage_status"], "exact")
        self.assertEqual(self.db.execute(relations[0]["source_sql"]).fetchall(), [(2,20)])
        self.assertEqual(relations[1]["lineage_status"], "unsupported")
        self.assertFalse(relations[1]["source_sql"])

    def test_failed_source_returns_diagnostic_without_breaking_workspace(self):
        from autocompare_tool.app_config import DatabaseWorkspaceConfig
        config = DatabaseWorkspaceConfig(page_size=2, max_page_size=100, export_batch_size=2,
                                         query_timeout_seconds=30, workspace_spool_limit_mb=10,
                                         write_mode_timeout_minutes=5)
        manager = SqlDatabaseWorkspaceManager(config)
        self.addCleanup(manager.close)
        workspace = manager._create_workspace(None, "test", "sqlite")
        adapter = SqlServerAdapter()
        sql = "SELECT id FROM A WHERE id=2"
        with patch.object(adapter, "get_relation", return_value=self.metadata()[0]), \
             patch.object(adapter, "execute", side_effect=RuntimeError("source unavailable")):
            manager._analyze_and_spool_sources(workspace, adapter, self.db, sql,
                                              parse_sql_expressions(sql, "sqlite"), "sqlite")
        response = manager._workspace_response(workspace)
        self.assertEqual(response["sources"][0]["lineage_status"], "unsupported")
        self.assertEqual(response["sources"][0]["item_id"], "")
        self.assertFalse(response["sources"][0]["updateable"])

    def test_framed_window_uses_only_selected_frame(self):
        self.assert_replays("WITH x AS (SELECT id,SUM(value) OVER(ORDER BY id ROWS 1 PRECEDING) AS running FROM A) SELECT * FROM x WHERE id=3",
                            {"A": {(2,20),(3,20)}})

    def test_window_following_frame(self):
        self.assert_replays("WITH x AS (SELECT id,SUM(value) OVER(ORDER BY id ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING) AS total FROM A) SELECT * FROM x WHERE id=2",
                            {"A": {(2,20),(3,20)}})

    def test_default_window_range_retains_peers(self):
        self.assert_replays("WITH x AS (SELECT id,SUM(value) OVER(ORDER BY value) AS total FROM A) SELECT * FROM x WHERE id=2",
                            {"A": {(1,10),(2,20),(3,20)}})

    def test_lag_only_traces_offset_row(self):
        self.assert_replays("WITH x AS (SELECT id,LAG(value) OVER(ORDER BY id) AS previous FROM A) SELECT * FROM x WHERE id=3",
                            {"A": {(2,20),(3,20)}})

    def test_window_over_grouped_members(self):
        self.assert_replays("WITH x AS (SELECT value,SUM(COUNT(*)) OVER(ORDER BY value ROWS 1 PRECEDING) AS total FROM A GROUP BY value) SELECT * FROM x WHERE value=20",
                            {"A": {(1,10),(2,20),(3,20)}})

    def test_exact_group_members_are_paged_and_exported_without_negative_rows(self):
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
        sql = "SELECT value,COUNT(*) FROM A GROUP BY value HAVING COUNT(*)>1"
        with patch.object(adapter, "get_relation", return_value=metadata):
            manager._analyze_and_spool_sources(workspace, adapter, self.db, sql,
                                              parse_sql_expressions(sql, "sqlite"), "sqlite")
        source = workspace.sources[0]
        self.assertEqual(source["lineage_status"], "exact", source)
        self.assertEqual(source["row_count"], 2)
        page = manager.get_page(workspace.workspace_id, source["item_id"], page=1)
        self.assertEqual(len(page["rows"]), 2)
        with patch("autocompare_tool.sql_database_workspace._find_negative_row") as negative:
            exported = manager._export_one_source(workspace, source, workspace.relations[source["relation_id"]],
                                                  self.db, adapter, workspace.root_path, lambda _: None)
        negative.assert_not_called()
        self.assertEqual(exported["negative_record_count"], 0)
        self.assertEqual(read_dbeaver_csv(Path(exported["path"])).rows,
                         [["2","20"],["3","20"]])


if __name__ == "__main__":
    unittest.main()
