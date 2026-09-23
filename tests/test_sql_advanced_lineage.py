"""Executable SQL regression tests; install requirements-test.txt for DuckDB."""

import unittest
from collections import Counter

try:
    import duckdb
except ImportError:
    duckdb = None

from sqlglot import exp, parse_one

from autocompare_tool.database_io import DatabaseColumn, PostgreSqlAdapter, SqlServerAdapter, TableMetadata
from autocompare_tool.sql_database_workspace import _diagnostic_source_sql
from autocompare_tool.sql_tools import analyze_sql, parse_sql_expressions


@unittest.skipIf(duckdb is None, "Install requirements-test.txt to execute advanced SQL lineage tests")
class AdvancedLineageTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect(":memory:")
        self.addCleanup(self.db.close)
        self.ddl = """
            CREATE TABLE A(id INTEGER PRIMARY KEY,value INTEGER);
            CREATE TABLE B(id INTEGER PRIMARY KEY,aid INTEGER);
            CREATE TABLE Nodes(id INTEGER PRIMARY KEY,parent_id INTEGER);
            CREATE TABLE Sales(id INTEGER PRIMARY KEY,region INTEGER,category VARCHAR,amount INTEGER);
        """
        self.db.execute(self.ddl)
        self.db.execute("""
            INSERT INTO A VALUES (1,10),(2,20),(3,20),(4,40);
            INSERT INTO B VALUES (11,1),(12,2),(13,3),(14,9),(15,2);
            INSERT INTO Nodes VALUES (1,NULL),(2,1),(3,2),(4,1),(5,NULL),(6,5);
            INSERT INTO Sales VALUES (1,1,'a',10),(2,1,'b',20),(3,1,'c',30),(4,2,'a',40),(5,2,'b',50);
        """)
        self.metadata = [TableMetadata(schema="main", name=table, columns=[
            DatabaseColumn(name=name, ordinal=index, data_type="varchar" if name == "category" else "int", is_primary_key=index==1)
            for index, name in enumerate(columns,1)
        ]) for table,columns in [
            ("A",["id","value"]), ("B",["id","aid"]),
            ("Nodes",["id","parent_id"]), ("Sales",["id","region","category","amount"]),
        ]]

    def executable(self, sql, dialect):
        query = parse_one(sql, read=dialect)
        for with_ in query.find_all(exp.With):
            with_.set("recursive", True)
        for join in query.find_all(exp.Join):
            if isinstance(join.this, exp.Lateral) and not join.args.get("on") and join.args.get("kind") != "CROSS":
                cross_apply = join.this.args.get("cross_apply")
                if cross_apply is not None:
                    join.this.set("cross_apply", None)
                    join.set("side", "LEFT" if not cross_apply else None)
                join.set("on", exp.true())
        return query.sql(dialect="duckdb")

    def assert_sources(self, sql, expected, dialect="tsql", replay=True):
        original = Counter(self.db.execute(self.executable(sql,dialect)).fetchall())
        parsed = parse_sql_expressions(sql,dialect)[0]
        actual = {}
        for ref in analyze_sql(sql,dialect).tables:
            if ref.source_type != "TABLE":
                continue
            metadata = next((item for item in self.metadata if item.name.casefold()==ref.name.casefold()), None)
            self.assertIsNotNone(metadata, ref)
            adapter = SqlServerAdapter() if dialect=="tsql" else PostgreSqlAdapter()
            source, reason, trace, _ = _diagnostic_source_sql(parsed,ref,metadata,adapter,dialect,self.metadata)
            self.assertTrue(source, reason)
            try:
                rows = self.db.execute(self.executable(source,dialect)).fetchall()
            except Exception as exc:
                self.fail(f"{exc}\n{source}")
            actual.setdefault(metadata.name,set()).update(rows)
        self.assertEqual(actual,expected)
        if replay:
            with duckdb.connect(":memory:") as database:
                database.execute(self.ddl)
                for table, rows in actual.items():
                    if rows:
                        database.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in next(iter(rows)))})",list(rows))
                self.assertEqual(Counter(database.execute(self.executable(sql,dialect)).fetchall()), original)

    def test_cross_apply_top_correlates_each_left_record(self):
        self.assert_sources("SELECT a.id,x.id AS bid FROM A a CROSS APPLY (SELECT TOP 1 b.id FROM B b WHERE b.aid=a.id ORDER BY b.id DESC) x WHERE a.id=2",
                            {"A": {(2,20)}, "B": {(15,2)}})

    def test_outer_apply_keeps_unmatched_left_record(self):
        self.assert_sources("SELECT a.id,x.id AS bid FROM A a OUTER APPLY (SELECT b.id FROM B b WHERE b.aid=a.id) x WHERE a.id=4",
                            {"A": {(4,40)}, "B": set()})

    def test_apply_grouped_query(self):
        self.assert_sources("SELECT a.id,x.n FROM A a CROSS APPLY (SELECT COUNT(*) AS n FROM B b WHERE b.aid=a.id) x WHERE a.id=2",
                            {"A": {(2,20)}, "B": {(12,2),(15,2)}})

    def test_rollup_only_selected_subtotal(self):
        self.assert_sources("WITH x AS (SELECT region,category,SUM(amount) AS total,GROUPING(category) AS g FROM Sales GROUP BY ROLLUP(region,category)) SELECT * FROM x WHERE region=1 AND g=1",
                            {"Sales": {(1,1,"a",10),(2,1,"b",20),(3,1,"c",30)}})

    def test_grouping_sets_only_selected_detail(self):
        self.assert_sources("WITH x AS (SELECT region,category,SUM(amount) AS total,GROUPING(category) AS g FROM Sales GROUP BY GROUPING SETS((region,category),(region),())) SELECT * FROM x WHERE region=1 AND category='b' AND g=0",
                            {"Sales": {(2,1,"b",20)}})

    def test_recursive_cte_keeps_ancestors_of_selected_leaf(self):
        self.assert_sources("WITH RECURSIVE tree(id,parent_id) AS (SELECT id,parent_id FROM Nodes WHERE parent_id IS NULL UNION ALL SELECT n.id,n.parent_id FROM Nodes n JOIN tree t ON n.parent_id=t.id) SELECT id FROM tree WHERE id=3",
                            {"Nodes": {(1,None),(2,1),(3,2)}}, dialect="postgres")

    def test_tsql_recursive_cte_without_recursive_keyword(self):
        self.assert_sources("WITH tree AS (SELECT id,parent_id FROM Nodes WHERE parent_id IS NULL UNION ALL SELECT n.id,n.parent_id FROM Nodes n JOIN tree t ON n.parent_id=t.id) SELECT id FROM tree WHERE id=3",
                            {"Nodes": {(1,None),(2,1),(3,2)}})

    def test_recursive_distinct_cycle_terminates_and_keeps_path(self):
        self.db.execute("UPDATE Nodes SET parent_id=3 WHERE id=1")
        self.assert_sources("WITH RECURSIVE tree(id,parent_id) AS (SELECT id,parent_id FROM Nodes WHERE id=1 UNION SELECT n.id,n.parent_id FROM Nodes n JOIN tree t ON n.parent_id=t.id) SELECT id FROM tree WHERE id=3",
                            {"Nodes": {(1,3),(2,1),(3,2)}}, dialect="postgres")

    def test_pivot_only_selected_group(self):
        self.assert_sources("SELECT p.region,p.a,p.b FROM (SELECT region,category,amount FROM Sales) s PIVOT(SUM(amount) FOR category IN ([a],[b])) p WHERE p.region=1",
                            {"Sales": {(1,1,"a",10),(2,1,"b",20),(3,1,"c",30)}})

    def test_cube_only_selected_category(self):
        self.assert_sources("WITH x AS (SELECT region,category,SUM(amount) AS total,GROUPING(region) AS g FROM Sales GROUP BY CUBE(region,category)) SELECT * FROM x WHERE category='a' AND g=1",
                            {"Sales": {(1,1,"a",10),(4,2,"a",40)}})

    def test_except_all_keeps_duplicate_multiplicities(self):
        self.assert_sources("SELECT aid FROM B WHERE aid=2 EXCEPT ALL SELECT id FROM A WHERE id=2",
                            {"A": {(2,20)}, "B": {(12,2),(15,2)}},dialect="postgres")

    def test_distinct_on_with_limit_and_order(self):
        self.assert_sources("SELECT DISTINCT ON(value) id,value FROM A ORDER BY value DESC,id DESC LIMIT 1",
                            {"A": {(4,40)}},dialect="postgres")

    def test_distinct_on_without_limit_preserves_selected_rows(self):
        self.assert_sources("SELECT DISTINCT ON(value) id,value FROM A ORDER BY value,id DESC",
                            {"A": {(1,10),(3,20),(4,40)}}, dialect="postgres")

    def test_filtered_window_aggregate(self):
        self.assert_sources("WITH x AS (SELECT id,SUM(value) FILTER(WHERE id<>1) OVER(ORDER BY id ROWS 1 PRECEDING) AS total FROM A) SELECT * FROM x WHERE id=3",
                            {"A": {(2,20),(3,20)}}, dialect="postgres")

    def test_lag_larger_offset_keeps_intermediate_ordering_rows(self):
        self.assert_sources("WITH x AS (SELECT id,LAG(value,2) OVER(ORDER BY id) AS previous FROM A) SELECT * FROM x WHERE id=4",
                            {"A": {(2,20),(3,20),(4,40)}})

    def test_named_window(self):
        self.assert_sources("WITH x AS (SELECT id,SUM(value) OVER w AS total FROM A WINDOW w AS (PARTITION BY value ORDER BY id ROWS 1 PRECEDING)) SELECT * FROM x WHERE id=3",
                            {"A": {(2,20),(3,20)}}, dialect="postgres")

    def test_dynamic_lag_offset(self):
        self.assert_sources("WITH x AS (SELECT id,LAG(value,CASE WHEN id>2 THEN id-2 ELSE 1 END) OVER(ORDER BY id) AS previous FROM A) SELECT * FROM x WHERE id=4",
                            {"A": {(2,20),(3,20),(4,40)}})

    def test_lag_ignores_null_values_but_preserves_order(self):
        self.db.execute("UPDATE A SET value=NULL WHERE id=3")
        self.assert_sources("WITH x AS (SELECT id,LAG(value) IGNORE NULLS OVER(ORDER BY id) AS previous FROM A) SELECT * FROM x WHERE id=4",
                            {"A": {(2,20),(3,None),(4,40)}})

    def test_lead_ignore_nulls_beyond_partition(self):
        self.db.execute("UPDATE A SET value=NULL WHERE id=3")
        self.assert_sources("WITH x AS (SELECT id,LEAD(value,2,0) IGNORE NULLS OVER(ORDER BY id) AS following FROM A) SELECT * FROM x WHERE id=2",
                            {"A": {(2,20),(3,None),(4,40)}})

    def test_frame_gap_keeps_intermediate_positions(self):
        self.assert_sources("WITH x AS (SELECT id,SUM(value) OVER(ORDER BY id ROWS BETWEEN 2 PRECEDING AND 2 PRECEDING) AS total FROM A) SELECT * FROM x WHERE id=4",
                            {"A": {(2,20),(3,20),(4,40)}})

    def test_recursive_cte_uses_previous_cte_and_reused_result(self):
        self.assert_sources("WITH RECURSIVE seeds AS (SELECT id,parent_id FROM Nodes WHERE parent_id IS NULL),tree AS (SELECT * FROM seeds UNION ALL SELECT n.id,n.parent_id FROM Nodes n JOIN tree t ON n.parent_id=t.id) SELECT t.id,p.id FROM tree t JOIN tree p ON t.parent_id=p.id WHERE t.id=3",
                            {"Nodes": {(1,None),(2,1),(3,2)}}, dialect="postgres")

    def test_tuple_in_matches_all_columns(self):
        self.assert_sources("SELECT a.id FROM A a WHERE a.id=2 AND (a.id,a.id) IN (SELECT b.aid,b.id-10 FROM B b)",
                            {"A": {(2,20)}, "B": {(12,2)}},dialect="postgres")

    def test_semi_join_keeps_matching_rows(self):
        self.assert_sources("SELECT a.id FROM A a SEMI JOIN B b ON b.aid=a.id WHERE a.id=2",
                            {"A": {(2,20)}, "B": {(12,2),(15,2)}},dialect="duckdb")

    def test_anti_join_keeps_unmatched_rows(self):
        self.assert_sources("SELECT a.id FROM A a ANTI JOIN B b ON b.aid=a.id WHERE a.id=4",
                            {"A": {(4,40)}, "B": set()},dialect="duckdb")

    def test_natural_join_uses_schema_columns(self):
        self.assert_sources("SELECT a.id FROM A a NATURAL JOIN (SELECT aid AS id FROM B) b WHERE a.id=2",
                            {"A": {(2,20)}, "B": {(12,2),(15,2)}},dialect="postgres")

    def test_unpivot_retains_selected_input_record(self):
        self.assert_sources("SELECT u.id,u.kind,u.v FROM (SELECT id,value,value*2 AS other FROM A) s UNPIVOT(v FOR kind IN(value,other)) u WHERE u.id=2 AND u.kind='other'",
                            {"A": {(2,20)}})

    def test_union_by_name_respects_outer_filter(self):
        self.assert_sources("SELECT id FROM (SELECT id,value AS amount FROM A UNION ALL BY NAME SELECT aid AS id,id AS amount FROM B) x WHERE id=2",
                            {"A": {(2,20)}, "B": {(12,2),(15,2)}},dialect="duckdb")
