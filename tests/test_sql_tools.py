from __future__ import annotations

import unittest

from autocompare_tool.sql_tools import analyze_sql, format_sql


COMPLEX_SQL = """
WITH recent_orders AS (
  SELECT o.id, o.customer_id, o.total
  FROM sales.orders o
  WHERE o.created_at >= '2026-01-01' AND o.status = 'PAID'
), customer_totals AS (
  SELECT r.customer_id, SUM(r.total) AS total_paid
  FROM recent_orders r
  GROUP BY r.customer_id
)
SELECT c.id, c.name, ct.total_paid, p.last_payment
FROM dbo.customers c
JOIN customer_totals ct ON ct.customer_id = c.id AND ct.total_paid > 100
LEFT JOIN (
  SELECT customer_id, MAX(paid_at) AS last_payment
  FROM billing.payments p
  WHERE p.state = 'SUCCESS'
  GROUP BY customer_id
) p ON p.customer_id = c.id
WHERE c.active = 1
  AND EXISTS (
    SELECT 1 FROM audit.customer_flags f
    WHERE f.customer_id = c.id AND f.blocked = 0
  )
ORDER BY ct.total_paid DESC
"""


class SqlToolsTests(unittest.TestCase):
    def test_formats_ugly_sql_and_multiple_statements(self) -> None:
        result = format_sql(
            "select a,b,sum(c) total from dbo.orders o where a=1 and b in(1,2) group by a,b;select * from x",
            "tsql",
        )

        self.assertEqual(2, result.statement_count)
        self.assertIn("SELECT\n  a,\n  b,", result.formatted_sql)
        self.assertIn("FROM dbo.orders AS o", result.formatted_sql)
        self.assertIn("\nWHERE\n", result.formatted_sql)
        self.assertIn(";\n\nSELECT", result.formatted_sql)

    def test_analyzes_all_tables_aliases_conditions_ctes_and_subqueries(self) -> None:
        result = analyze_sql(COMPLEX_SQL, "tsql")

        table_pairs = [(item.qualified_name, item.alias, item.source_type) for item in result.tables]
        self.assertIn(("sales.orders", "o", "TABLE"), table_pairs)
        self.assertIn(("recent_orders", "r", "CTE_REFERENCE"), table_pairs)
        self.assertIn(("dbo.customers", "c", "TABLE"), table_pairs)
        self.assertIn(("customer_totals", "ct", "CTE_REFERENCE"), table_pairs)
        self.assertIn(("billing.payments", "p", "TABLE"), table_pairs)
        self.assertIn(("audit.customer_flags", "f", "TABLE"), table_pairs)
        self.assertEqual(6, len(result.tables))

        self.assertEqual(["recent_orders", "customer_totals"], [item.name for item in result.ctes])
        self.assertTrue(any(item.subquery_type == "DERIVED TABLE" and item.alias == "p" for item in result.subqueries))
        self.assertTrue(any(item.subquery_type == "EXISTS" for item in result.subqueries))

        clauses = [item.clause for item in result.conditions]
        self.assertGreaterEqual(clauses.count("WHERE"), 5)
        self.assertTrue(any(clause.endswith("JOIN ON") for clause in clauses))
        self.assertTrue(any("ct.total_paid > 100" in item.expression for item in result.conditions))
        self.assertTrue(any("f.blocked = 0" in item.expression for item in result.conditions))
        self.assertTrue(any(item.clause == "GROUP BY" for item in result.clauses))
        self.assertTrue(any(item.clause == "ORDER BY" for item in result.clauses))
        self.assertGreaterEqual(len(result.projections), 10)

    def test_keeps_every_self_join_table_occurrence(self) -> None:
        result = analyze_sql(
            "SELECT a.id FROM employee a JOIN employee b ON b.manager_id=a.id JOIN employee c ON c.id=b.id",
            "",
        )

        self.assertEqual(["a", "b", "c"], [item.alias for item in result.tables])
        self.assertEqual(3, len(result.tables))
        self.assertEqual(2, len([item for item in result.conditions if item.clause.endswith("JOIN ON")]))

    def test_analyzes_large_join_chain_without_an_application_limit(self) -> None:
        joins = " ".join(
            f"JOIN table_{index} t{index} ON t{index}.parent_id = t{index - 1}.id"
            for index in range(1, 121)
        )

        result = analyze_sql(f"SELECT t0.id FROM table_0 t0 {joins}")

        self.assertEqual(121, len(result.tables))
        self.assertEqual(120, len([item for item in result.conditions if item.clause.endswith("JOIN ON")]))

    def test_analyzes_oracle_hierarchical_conditions(self) -> None:
        result = analyze_sql(
            "SELECT id FROM employees START WITH manager_id IS NULL CONNECT BY PRIOR id = manager_id",
            "oracle",
        )

        self.assertIn("START WITH", [item.clause for item in result.conditions])
        self.assertIn("CONNECT BY", [item.clause for item in result.conditions])

    def test_detects_dml_target_and_source_tables(self) -> None:
        result = analyze_sql(
            "INSERT INTO archive.orders (id) SELECT o.id FROM sales.orders o WHERE o.closed = 1",
            "tsql",
        )

        targets = [item for item in result.tables if item.role == "INSERT TARGET"]
        self.assertEqual(["archive.orders"], [item.qualified_name for item in targets])
        self.assertTrue(any(item.qualified_name == "sales.orders" and item.role == "FROM" for item in result.tables))

    def test_reports_parser_location_for_invalid_sql(self) -> None:
        with self.assertRaisesRegex(ValueError, r"dòng 1, cột"):
            analyze_sql("SELECT * FROM (SELECT id FROM users", "postgres")

    def test_rejects_unknown_dialect(self) -> None:
        with self.assertRaisesRegex(ValueError, "dialect không được hỗ trợ"):
            format_sql("SELECT 1", "not-a-dialect")

    def test_requires_sql_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "Vui lòng nhập"):
            analyze_sql("   ")


if __name__ == "__main__":
    unittest.main()
