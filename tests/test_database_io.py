from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from autocompare_tool.dbeaver_csv import DbeaverCsv
from autocompare_tool.database_io import (
    DatabaseAdapter,
    DatabaseColumn,
    DatabaseConnectionSettings,
    DatabaseCsvSummary,
    OracleAdapter,
    PostgreSqlAdapter,
    SqlServerAdapter,
    TableMetadata,
    _build_export_select_sql,
    _build_import_mapping,
    _format_csv_value,
    _format_db_value,
    _import_one_csv,
    _sqlserver_type_name,
    normalize_database_type,
    validate_connection_settings,
)


class DatabaseIoTests(unittest.TestCase):
    def test_normalize_database_type_accepts_common_aliases(self) -> None:
        self.assertEqual(normalize_database_type("SQL Server"), "sqlserver")
        self.assertEqual(normalize_database_type("postgress"), "postgresql")
        self.assertEqual(normalize_database_type("oracel"), "oracle")

    def test_validate_connection_defaults_schema_by_database_type(self) -> None:
        settings = validate_connection_settings(
            DatabaseConnectionSettings(
                database_type="PostgreSQL",
                host="localhost",
                database="sample",
                username="tester",
            )
        )

        self.assertEqual(settings.schema, "public")
        self.assertEqual(settings.port, "5432")

    def test_import_mapping_skips_generated_and_identity_when_not_kept(self) -> None:
        table = DbeaverCsv(
            headers=["id", "name", "total", "rv", "amount"],
            rows=[["10", "Alice", "calc", "abc", "12.3"]],
        )
        columns = [
            _column("id", is_identity=True),
            _column("name", data_type="varchar"),
            _column("total", data_type="numeric", is_computed=True),
            _column("rv", data_type="rowversion"),
            _column("amount", data_type="numeric", numeric_scale=4),
        ]

        mapping = _build_import_mapping(table, columns, SqlServerAdapter(), keep_identity=False)

        self.assertEqual([column.name for column in mapping.columns], ["name", "amount"])
        self.assertEqual(
            mapping.skipped_columns,
            (
                "id (identity được CSDL tự sinh)",
                "total (computed/generated)",
                "rv (rowversion/timestamp)",
            ),
        )

    def test_import_mapping_keeps_identity_when_supported(self) -> None:
        table = DbeaverCsv(headers=["id", "name"], rows=[["10", "Alice"]])
        columns = [_column("id", is_identity=True), _column("name", data_type="varchar")]

        mapping = _build_import_mapping(table, columns, SqlServerAdapter(), keep_identity=True)

        self.assertEqual([column.name for column in mapping.columns], ["id", "name"])

    def test_postgresql_timestamp_is_insertable(self) -> None:
        table = DbeaverCsv(headers=["created_at"], rows=[["2026-06-29 01:02:03"]])
        columns = [_column("created_at", data_type="timestamp without time zone")]

        mapping = _build_import_mapping(table, columns, PostgreSqlAdapter(), keep_identity=False)

        self.assertEqual([column.name for column in mapping.columns], ["created_at"])
        self.assertEqual(_sqlserver_type_name("timestamp"), "rowversion")

    def test_oracle_generated_always_identity_is_not_insertable(self) -> None:
        table = DbeaverCsv(headers=["id", "name"], rows=[["10", "Alice"]])
        columns = [
            _column("id", is_identity=True, identity_generation="ALWAYS"),
            _column("name", data_type="varchar2"),
        ]

        mapping = _build_import_mapping(table, columns, OracleAdapter(), keep_identity=True)

        self.assertEqual([column.name for column in mapping.columns], ["name"])
        self.assertEqual(mapping.skipped_columns, ("id (CSDL không cho nhập identity GENERATED ALWAYS)",))

    def test_postgresql_insert_sql_uses_overriding_system_value_when_identity_is_kept(self) -> None:
        metadata = TableMetadata(schema="public", name="customers", columns=[])
        columns = [_column("id", is_identity=True), _column("name", data_type="varchar")]

        sql = PostgreSqlAdapter().insert_sql(metadata, columns, keep_identity=True)

        self.assertIn("OVERRIDING SYSTEM VALUE", sql)

    def test_export_select_orders_by_primary_key(self) -> None:
        adapter = SqlServerAdapter()
        metadata = TableMetadata(
            schema="dbo",
            name="orders",
            columns=[
                _column("id", is_primary_key=True),
                _column("name", data_type="nvarchar"),
            ],
        )

        sql = _build_export_select_sql(adapter, metadata, metadata.columns)

        self.assertEqual(sql, "SELECT [id], [name] FROM [dbo].[orders] ORDER BY [id]")

    def test_formats_db_and_csv_values_by_metadata(self) -> None:
        amount = _column("amount", data_type="numeric", numeric_scale=4)
        created_at = _column("created_at", data_type="datetime")

        self.assertEqual(_format_db_value(Decimal("12.3"), amount), "12.3000")
        self.assertEqual(_format_db_value(datetime(2026, 6, 29, 1, 2, 3, 456789), created_at), "2026-06-29 01:02:03.456")
        self.assertEqual(_format_csv_value("3456.0", amount), "3456.0000")
        self.assertEqual(_format_csv_value("2026/06/29", created_at), "2026-06-29 00:00:00.000")

    def test_import_cleanup_runs_after_insert_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "customers.csv"
            csv_path.write_text('id,name\r\n"1","Alice"\r\n', encoding="utf-8")
            adapter = FailingIdentityAdapter()
            connection = FakeConnection()
            summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=root)

            _import_one_csv(
                connection,
                adapter,
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="sample", schema="dbo"),
                root,
                csv_path,
                True,
                summary,
                lambda _message: None,
            )

            self.assertEqual(adapter.calls, ["before", "executemany", "after"])
            self.assertEqual(summary.error_count, 1)
            self.assertTrue(connection.rolled_back)


def _column(
    name: str,
    data_type: str = "int",
    is_identity: bool = False,
    identity_generation: str = "",
    is_computed: bool = False,
    generated_expression: str | None = None,
    numeric_scale: int | None = None,
    is_primary_key: bool = False,
) -> DatabaseColumn:
    return DatabaseColumn(
        name=name,
        ordinal=1,
        data_type=data_type,
        is_identity=is_identity,
        identity_generation=identity_generation,
        is_computed=is_computed,
        generated_expression=generated_expression,
        numeric_scale=numeric_scale,
        is_primary_key=is_primary_key,
    )


class FakeConnection:
    def __init__(self) -> None:
        self.rolled_back = False

    def cursor(self) -> object:
        return object()

    def commit(self) -> None:
        raise AssertionError("commit should not be called after insert error")

    def rollback(self) -> None:
        self.rolled_back = True


class FailingIdentityAdapter(DatabaseAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_table(self, _connection, _settings, _table_name: str, schema: str | None = None) -> TableMetadata:
        return TableMetadata(
            schema=schema or "dbo",
            name="customers",
            columns=[
                _column("id", is_identity=True),
                _column("name", data_type="varchar"),
            ],
        )

    def before_import(self, _cursor, _metadata, _columns, _keep_identity: bool) -> None:
        self.calls.append("before")

    def executemany(self, _cursor, _sql: str, _rows) -> None:
        self.calls.append("executemany")
        raise RuntimeError("insert failed")

    def after_import(self, _cursor, _metadata, _columns, _keep_identity: bool) -> None:
        self.calls.append("after")


if __name__ == "__main__":
    unittest.main()
