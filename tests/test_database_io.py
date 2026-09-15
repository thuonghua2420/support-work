from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from autocompare_tool.dbeaver_csv import DbeaverCsv, read_dbeaver_csv
from autocompare_tool.database_io import (
    DatabaseAdapter,
    DatabaseColumn,
    DatabaseConnectionSettings,
    DatabaseCsvSummary,
    DatabaseSyncSummary,
    IMPORT_MODE_DELETE_MATCHING_KEYS,
    IMPORT_MODE_TRUNCATE_TABLE,
    SYNC_DUPLICATE_UPSERT,
    SYNC_MODE_CONDITION,
    SYNC_MODE_INCREMENTAL,
    OracleAdapter,
    PostgreSqlAdapter,
    SqlServerAdapter,
    TableMetadata,
    _build_export_select_sql,
    _build_delete_by_primary_key_sql,
    _build_import_mapping,
    _build_sync_columns,
    _build_sync_select_sql,
    _build_sync_update_sql,
    _format_csv_value,
    _format_db_value,
    _import_one_csv,
    _parse_record_limit,
    _parse_sync_batch_size,
    _sync_one_table,
    _sqlserver_type_name,
    build_update_by_primary_key_sql,
    canonical_row_hash,
    import_csv_folder,
    normalize_database_type,
    scan_import_csv_tables,
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

    def test_delete_by_primary_key_sql_supports_composite_keys(self) -> None:
        adapter = SqlServerAdapter()
        metadata = TableMetadata(
            schema="dbo",
            name="orders",
            columns=[
                _column("tenant_id", is_primary_key=True),
                _column("id", is_primary_key=True),
                _column("name", data_type="nvarchar"),
            ],
        )

        sql = _build_delete_by_primary_key_sql(adapter, metadata)

        self.assertEqual(
            sql,
            "DELETE FROM [dbo].[orders] WHERE [tenant_id] = ? AND [id] = ?",
        )

    def test_public_update_sql_and_canonical_hash_support_composite_keys(self) -> None:
        adapter = SqlServerAdapter()
        metadata = TableMetadata(
            schema="dbo",
            name="orders",
            columns=[
                _column("tenant_id", is_primary_key=True),
                _column("id", is_primary_key=True),
                _column("name", data_type="nvarchar"),
            ],
        )

        sql = build_update_by_primary_key_sql(adapter, metadata, [metadata.columns[2]], metadata.columns[:2])
        first_hash = canonical_row_hash(("A", 1, "Alice"), metadata.columns)
        second_hash = canonical_row_hash(("A", 1, "Alice"), metadata.columns)

        self.assertEqual(sql, "UPDATE [dbo].[orders] SET [name] = ? WHERE [tenant_id] = ? AND [id] = ?")
        self.assertEqual(first_hash, second_hash)

    def test_sync_select_orders_by_primary_key_even_when_identity_is_skipped(self) -> None:
        adapter = SqlServerAdapter()
        metadata = TableMetadata(
            schema="dbo",
            name="orders",
            columns=[
                _column("id", is_identity=True, is_primary_key=True),
                _column("name", data_type="nvarchar"),
            ],
        )

        sql = _build_sync_select_sql(adapter, metadata, [_column("name", data_type="nvarchar")])

        self.assertEqual(sql, "SELECT [name] FROM [dbo].[orders] ORDER BY [id]")

    def test_sync_select_supports_where_clause_before_order_by(self) -> None:
        adapter = SqlServerAdapter()
        metadata = TableMetadata(
            schema="dbo",
            name="orders",
            columns=[
                _column("id", data_type="int", is_primary_key=True),
                _column("status", data_type="nvarchar"),
            ],
        )

        sql = _build_sync_select_sql(
            adapter,
            metadata,
            metadata.columns,
            where_clause="WHERE status = 'ACTIVE'",
        )

        self.assertEqual(
            sql,
            "SELECT [id], [status] FROM [dbo].[orders] WHERE (status = 'ACTIVE') ORDER BY [id]",
        )

    def test_build_sync_columns_skips_non_insertable_target_columns(self) -> None:
        source_metadata = TableMetadata(
            schema="dbo",
            name="customers",
            columns=[
                _column("id", is_identity=True),
                _column("name", data_type="nvarchar"),
                _column("total", data_type="numeric", is_computed=True),
                _column("rv", data_type="rowversion"),
            ],
        )
        target_metadata = TableMetadata(
            schema="dbo",
            name="customers",
            columns=[
                _column("id", is_identity=True),
                _column("name", data_type="nvarchar"),
                _column("total", data_type="numeric", is_computed=True),
                _column("rv", data_type="rowversion"),
            ],
        )

        source_columns, target_columns, skipped = _build_sync_columns(
            source_metadata,
            target_metadata,
            SqlServerAdapter(),
            keep_identity=False,
        )

        self.assertEqual([column.name for column in source_columns], ["name"])
        self.assertEqual([column.name for column in target_columns], ["name"])
        self.assertEqual(
            skipped,
            (
                "id (identity được CSDL tự sinh)",
                "total (computed/generated)",
                "rv (rowversion/timestamp)",
            ),
        )

    def test_parse_record_limit_treats_blank_as_all_records(self) -> None:
        self.assertIsNone(_parse_record_limit(""))
        self.assertIsNone(_parse_record_limit(None))
        self.assertEqual(_parse_record_limit("25"), 25)
        with self.assertRaises(ValueError):
            _parse_record_limit("0")

    def test_sync_one_table_truncates_target_before_insert_when_enabled(self) -> None:
        metadata = TableMetadata(
            schema="dbo",
            name="customers",
            columns=[
                _column("id", is_identity=True),
                _column("name", data_type="nvarchar"),
            ],
        )
        source_adapter = SyncRecordingAdapter(metadata)
        target_adapter = SyncRecordingAdapter(metadata)
        source_connection = SyncConnection([(1, "Alice")])
        target_connection = SyncConnection([])
        summary = DatabaseSyncSummary()

        _sync_one_table(
            source_connection,
            target_connection,
            source_adapter,
            target_adapter,
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="source", schema="dbo"),
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="target", schema="dbo"),
            "customers",
            None,
            True,
            True,
            summary,
            lambda _message: None,
        )

        self.assertEqual(target_adapter.calls[0], ("truncate", "customers"))
        self.assertEqual(target_adapter.calls[1][0], "before")
        self.assertEqual(target_adapter.calls[2], ("executemany", [(1, "Alice")]))
        self.assertTrue(target_connection.committed)
        self.assertEqual(summary.table_count, 1)

    def test_incremental_sync_only_inserts_updates_and_deletes_differences(self) -> None:
        metadata = TableMetadata(
            schema="dbo",
            name="customers",
            columns=[
                _column("id", data_type="int", is_primary_key=True),
                _column("name", data_type="nvarchar"),
            ],
        )
        source_adapter = DeltaRecordingAdapter(metadata)
        target_adapter = DeltaRecordingAdapter(metadata)
        source_connection = SyncConnection([(1, "Alice"), (2, "Bob updated"), (4, "Dora")])
        target_read_connection = SyncConnection([(1, "Alice"), (2, "Bob"), (3, "Chris")])
        target_write_connection = SyncConnection([])
        summary = DatabaseSyncSummary()

        _sync_one_table(
            source_connection,
            target_write_connection,
            source_adapter,
            target_adapter,
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="source", schema="dbo"),
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="target", schema="dbo"),
            "customers",
            None,
            True,
            False,
            summary,
            lambda _message: None,
            sync_mode=SYNC_MODE_INCREMENTAL,
            batch_size=100,
            delete_target_only=True,
            target_read_connection=target_read_connection,
        )

        result = summary.table_results[0]
        self.assertEqual(result.source_row_count, 3)
        self.assertEqual(result.target_row_count, 3)
        self.assertEqual(result.inserted_count, 1)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.unchanged_count, 1)
        self.assertEqual(result.row_count, 3)
        self.assertEqual(target_adapter.rows_for("delete"), [(3,)])
        self.assertEqual(target_adapter.rows_for("update"), [("Bob updated", 2)])
        self.assertEqual(target_adapter.rows_for("insert"), [(4, "Dora")])
        self.assertTrue(target_write_connection.committed)
        self.assertFalse(target_write_connection.rolled_back)

    def test_condition_sync_upserts_and_backups_matching_target_keys(self) -> None:
        metadata = TableMetadata(
            schema="dbo",
            name="customers",
            columns=[
                _column("id", data_type="int", is_primary_key=True),
                _column("name", data_type="nvarchar"),
            ],
        )
        source_adapter = DeltaRecordingAdapter(metadata)
        target_adapter = DeltaRecordingAdapter(metadata)
        source_connection = ConditionalSyncConnection([(1, "Alice new"), (2, "Bob")])
        target_connection = ConditionalSyncConnection([(1, "Alice old"), (3, "Chris")])
        summary = DatabaseSyncSummary()

        with tempfile.TemporaryDirectory() as temp_dir:
            backup_dir = Path(temp_dir) / "backup"
            _sync_one_table(
                source_connection,
                target_connection,
                source_adapter,
                target_adapter,
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="source", schema="dbo"),
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="target", schema="dbo"),
                "customers",
                None,
                True,
                False,
                summary,
                lambda _message: None,
                sync_mode=SYNC_MODE_CONDITION,
                batch_size=100,
                where_clause="WHERE status = 'ACTIVE'",
                duplicate_mode=SYNC_DUPLICATE_UPSERT,
                backup_dir=backup_dir,
            )

            backup = read_dbeaver_csv(backup_dir / "dbo.customers.csv")

        result = summary.table_results[0]
        self.assertEqual(summary.error_count, 0)
        self.assertEqual(result.source_row_count, 2)
        self.assertEqual(result.target_row_count, 1)
        self.assertEqual(result.inserted_count, 1)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(result.backup_row_count, 1)
        self.assertEqual(target_adapter.rows_for("update"), [("Alice new", 1)])
        self.assertEqual(target_adapter.rows_for("insert"), [(2, "Bob")])
        self.assertEqual(backup.headers, ["id", "name"])
        self.assertEqual(backup.rows, [["1", "Alice old"]])
        self.assertTrue(target_connection.committed)

    def test_incremental_sync_compares_numeric_keys_in_database_order(self) -> None:
        metadata = TableMetadata(
            schema="dbo",
            name="numbers",
            columns=[
                _column("id", data_type="int", is_primary_key=True),
                _column("value", data_type="nvarchar"),
            ],
        )
        source_adapter = DeltaRecordingAdapter(metadata)
        target_adapter = DeltaRecordingAdapter(metadata)
        summary = DatabaseSyncSummary()

        _sync_one_table(
            SyncConnection([(2, "Two"), (10, "Ten")]),
            SyncConnection([]),
            source_adapter,
            target_adapter,
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="source", schema="dbo"),
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="target", schema="dbo"),
            "numbers",
            None,
            True,
            False,
            summary,
            lambda _message: None,
            sync_mode=SYNC_MODE_INCREMENTAL,
            batch_size=100,
            target_read_connection=SyncConnection([(10, "Ten")]),
        )

        result = summary.table_results[0]
        self.assertEqual(result.inserted_count, 1)
        self.assertEqual(result.unchanged_count, 1)
        self.assertEqual(result.deleted_count, 0)
        self.assertEqual(target_adapter.rows_for("insert"), [(2, "Two")])

    def test_incremental_sync_requires_matching_primary_keys(self) -> None:
        metadata = TableMetadata(
            schema="dbo",
            name="customers",
            columns=[_column("id", data_type="int"), _column("name", data_type="nvarchar")],
        )
        source_adapter = DeltaRecordingAdapter(metadata)
        target_adapter = DeltaRecordingAdapter(metadata)
        target_write_connection = SyncConnection([])
        summary = DatabaseSyncSummary()

        _sync_one_table(
            SyncConnection([(1, "Alice")]),
            target_write_connection,
            source_adapter,
            target_adapter,
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="source", schema="dbo"),
            DatabaseConnectionSettings(database_type="sqlserver", host=".", database="target", schema="dbo"),
            "customers",
            None,
            True,
            False,
            summary,
            lambda _message: None,
            sync_mode=SYNC_MODE_INCREMENTAL,
            batch_size=100,
            target_read_connection=SyncConnection([(1, "Alice")]),
        )

        self.assertEqual(summary.error_count, 1)
        self.assertIn("primary key", summary.errors[0].lower())
        self.assertFalse(target_write_connection.committed)

    def test_build_sync_update_sql_supports_composite_primary_key(self) -> None:
        adapter = SqlServerAdapter()
        metadata = TableMetadata(
            schema="dbo",
            name="orders",
            columns=[
                _column("tenant_id", is_primary_key=True),
                _column("id", is_primary_key=True),
                _column("name", data_type="nvarchar"),
            ],
        )

        sql = _build_sync_update_sql(
            adapter,
            metadata,
            [metadata.columns[2]],
            metadata.columns[:2],
        )

        self.assertEqual(
            sql,
            "UPDATE [dbo].[orders] SET [name] = ? WHERE [tenant_id] = ? AND [id] = ?",
        )

    def test_parse_sync_batch_size_applies_bounds_and_default(self) -> None:
        self.assertEqual(_parse_sync_batch_size(None), 5000)
        self.assertEqual(_parse_sync_batch_size("1000"), 1000)
        with self.assertRaises(ValueError):
            _parse_sync_batch_size("99")
        with self.assertRaises(ValueError):
            _parse_sync_batch_size("100001")

    def test_formats_db_and_csv_values_by_metadata(self) -> None:
        amount = _column("amount", data_type="numeric", numeric_scale=4)
        created_at = _column("created_at", data_type="datetime")

        self.assertEqual(_format_db_value(Decimal("12.3"), amount), "12.3000")
        self.assertEqual(_format_db_value(datetime(2026, 6, 29, 1, 2, 3, 456789), created_at), "2026-06-29 01:02:03.456")
        self.assertEqual(_format_csv_value("3456.0", amount), "3456.0000")
        self.assertEqual(_format_csv_value("2026/06/29", created_at), "2026-06-29 00:00:00.000")

    def test_import_csv_folder_reads_only_direct_csv_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            (root / "customers.csv").write_text('id,name\n"1","Alice"\n', encoding="utf-8")
            (nested / "orders.csv").write_text('id,name\n"2","Nested"\n', encoding="utf-8")
            metadata = TableMetadata(
                schema="dbo",
                name="customers",
                columns=[_column("id"), _column("name", data_type="nvarchar")],
            )
            adapter = RecordingImportAdapter(metadata)
            connection = RecordingImportConnection()
            adapter.connect = lambda _settings: connection

            with patch("autocompare_tool.database_io.get_adapter", return_value=adapter):
                summary = import_csv_folder(
                    root,
                    DatabaseConnectionSettings(
                        database_type="SQL Server",
                        host=".",
                        database="sample",
                        schema="dbo",
                        trusted_connection=True,
                    ),
                    log=lambda _message: None,
                )

            self.assertEqual(1, summary.csv_count)
            self.assertEqual("customers.csv", summary.csv_results[0].csv_path.name)
            self.assertEqual(1, summary.row_count)
            self.assertEqual(1, len([call for call in adapter.calls if call[0] == "executemany"]))
            self.assertTrue(connection.closed)

    def test_scan_import_csv_tables_reads_only_direct_csv_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            (root / "customers.csv").write_text('id,name\n"1","Alice"\n', encoding="utf-8")
            (root / "empty.csv").write_text("", encoding="utf-8")
            (nested / "orders.csv").write_text('id,name\n"2","Nested"\n', encoding="utf-8")

            tables = scan_import_csv_tables(root)

            self.assertEqual(["customers", "empty"], [table.table_name for table in tables])
            self.assertEqual([1, 0], [table.row_count for table in tables])
            self.assertEqual([True, False], [table.has_header for table in tables])

    def test_import_csv_folder_can_limit_to_selected_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "customers.csv").write_text('id,name\n"1","Alice"\n', encoding="utf-8")
            (root / "orders.csv").write_text('id,name\n"2","Skipped"\n', encoding="utf-8")
            metadata = TableMetadata(
                schema="dbo",
                name="customers",
                columns=[_column("id"), _column("name", data_type="nvarchar")],
            )
            adapter = RecordingImportAdapter(metadata)
            connection = RecordingImportConnection()
            adapter.connect = lambda _settings: connection
            requested_table_names: list[str] = []

            def get_table_spy(_connection, _settings, table_name: str, schema: str | None = None) -> TableMetadata:
                requested_table_names.append(table_name)
                return metadata

            adapter.get_table = get_table_spy

            with patch("autocompare_tool.database_io.get_adapter", return_value=adapter):
                summary = import_csv_folder(
                    root,
                    DatabaseConnectionSettings(
                        database_type="SQL Server",
                        host=".",
                        database="sample",
                        schema="dbo",
                        trusted_connection=True,
                    ),
                    table_names=["customers"],
                    log=lambda _message: None,
                )

            self.assertEqual(1, summary.csv_count)
            self.assertEqual("customers.csv", summary.csv_results[0].csv_path.name)
            self.assertEqual(["customers"], requested_table_names)
            self.assertEqual(1, len([call for call in adapter.calls if call[0] == "executemany"]))

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

    def test_import_preserves_null_and_empty_string_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "customers.csv"
            csv_path.write_text('id,empty_value,null_value\n"1","",\n', encoding="utf-8")
            metadata = TableMetadata(
                schema="dbo",
                name="customers",
                columns=[
                    _column("id", data_type="int"),
                    _column("empty_value", data_type="nvarchar"),
                    _column("null_value", data_type="nvarchar"),
                ],
            )
            adapter = RecordingImportAdapter(metadata)
            connection = RecordingImportConnection()
            summary = DatabaseCsvSummary(action_name="Nháº­p CSV vÃ o CSDL", root_path=root)

            _import_one_csv(
                connection,
                adapter,
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="sample", schema="dbo"),
                root,
                csv_path,
                False,
                summary,
                lambda _message: None,
            )

            insert_calls = [call for call in adapter.calls if call[0] == "executemany"]
            self.assertEqual(len(insert_calls), 1)
            self.assertEqual(insert_calls[0][2], [("1", "", None)])
            self.assertTrue(connection.committed)

    def test_import_deletes_matching_composite_primary_keys_before_insert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "orders.csv"
            csv_path.write_text(
                'tenant_id,id,name\n"A","1","First"\n"A","2","Second"\n',
                encoding="utf-8",
            )
            metadata = TableMetadata(
                schema="dbo",
                name="orders",
                columns=[
                    _column("tenant_id", is_primary_key=True),
                    _column("id", is_primary_key=True),
                    _column("name", data_type="nvarchar"),
                ],
            )
            adapter = RecordingImportAdapter(metadata)
            connection = RecordingImportConnection()
            summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=root)

            _import_one_csv(
                connection,
                adapter,
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="sample", schema="dbo"),
                root,
                csv_path,
                False,
                summary,
                lambda _message: None,
                IMPORT_MODE_DELETE_MATCHING_KEYS,
            )

            self.assertEqual(adapter.calls[0][0], "executemany")
            self.assertTrue(str(adapter.calls[0][1]).startswith("DELETE FROM"))
            self.assertEqual(adapter.calls[0][2], [("A", "1"), ("A", "2")])
            self.assertEqual(adapter.calls[1][0], "before")
            self.assertEqual(adapter.calls[2][0], "executemany")
            self.assertTrue(str(adapter.calls[2][1]).startswith("INSERT INTO"))
            self.assertEqual(adapter.calls[3][0], "after")
            self.assertTrue(connection.committed)
            self.assertEqual(summary.error_count, 0)

    def test_import_truncates_table_before_insert(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "customers.csv"
            csv_path.write_text('id,name\n"1","Alice"\n', encoding="utf-8")
            metadata = TableMetadata(
                schema="dbo",
                name="customers",
                columns=[_column("id", is_primary_key=True), _column("name", data_type="nvarchar")],
            )
            adapter = RecordingImportAdapter(metadata)
            connection = RecordingImportConnection()
            summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=root)

            _import_one_csv(
                connection,
                adapter,
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="sample", schema="dbo"),
                root,
                csv_path,
                False,
                summary,
                lambda _message: None,
                IMPORT_MODE_TRUNCATE_TABLE,
            )

            self.assertEqual(adapter.calls[0], ("truncate", "customers"))
            self.assertEqual(adapter.calls[1][0], "before")
            self.assertEqual(adapter.calls[2][0], "executemany")
            self.assertTrue(connection.committed)

    def test_delete_matching_keys_requires_importable_primary_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "customers.csv"
            csv_path.write_text('id,name\n"1","Alice"\n', encoding="utf-8")
            metadata = TableMetadata(
                schema="dbo",
                name="customers",
                columns=[
                    _column("id", is_identity=True, is_primary_key=True),
                    _column("name", data_type="nvarchar"),
                ],
            )
            adapter = RecordingImportAdapter(metadata)
            connection = RecordingImportConnection()
            summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=root)

            _import_one_csv(
                connection,
                adapter,
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="sample", schema="dbo"),
                root,
                csv_path,
                False,
                summary,
                lambda _message: None,
                IMPORT_MODE_DELETE_MATCHING_KEYS,
            )

            self.assertEqual(summary.error_count, 1)
            self.assertIn("hãy bật tùy chọn giữ identity", summary.errors[0])
            self.assertTrue(connection.rolled_back)
            self.assertFalse(connection.committed)

    def test_delete_matching_keys_rejects_duplicate_csv_keys_before_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / "customers.csv"
            csv_path.write_text(
                'id,name\n"1","Alice"\n"1","Alice updated"\n',
                encoding="utf-8",
            )
            metadata = TableMetadata(
                schema="dbo",
                name="customers",
                columns=[_column("id", is_primary_key=True), _column("name", data_type="nvarchar")],
            )
            adapter = RecordingImportAdapter(metadata)
            connection = RecordingImportConnection()
            summary = DatabaseCsvSummary(action_name="Nhập CSV vào CSDL", root_path=root)

            _import_one_csv(
                connection,
                adapter,
                DatabaseConnectionSettings(database_type="sqlserver", host=".", database="sample", schema="dbo"),
                root,
                csv_path,
                False,
                summary,
                lambda _message: None,
                IMPORT_MODE_DELETE_MATCHING_KEYS,
            )

            self.assertEqual(summary.error_count, 1)
            self.assertIn("primary key trùng", summary.errors[0])
            self.assertEqual(adapter.calls, [])
            self.assertTrue(connection.rolled_back)
            self.assertFalse(connection.committed)


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


class SyncConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> "SyncCursor":
        return SyncCursor(self.rows)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class SyncCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.index = 0

    def execute(self, *_args: object) -> None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        rows = self.rows[self.index : self.index + size]
        self.index += len(rows)
        return rows


class ConditionalSyncConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> "ConditionalSyncCursor":
        return ConditionalSyncCursor(self.rows)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class ConditionalSyncCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.source_rows = rows
        self.rows: list[tuple[object, ...]] = []
        self.index = 0

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.index = 0
        if "COUNT(*)" in sql:
            self.rows = [(len(self.source_rows),)]
        elif params:
            self.rows = [row for row in self.source_rows if row[: len(params)] == params]
        else:
            self.rows = list(self.source_rows)

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        rows = self.rows[self.index : self.index + size]
        self.index += len(rows)
        return rows

    def close(self) -> None:
        return None


class SyncRecordingAdapter(DatabaseAdapter):
    def __init__(self, metadata: TableMetadata) -> None:
        self.metadata = metadata
        self.calls: list[tuple[str, object]] = []

    def get_table(self, _connection, _settings, _table_name: str, schema: str | None = None) -> TableMetadata:
        return self.metadata

    def truncate_table(self, _cursor, metadata: TableMetadata) -> None:
        self.calls.append(("truncate", metadata.name))

    def before_import(self, _cursor, _metadata, columns: list[DatabaseColumn], _keep_identity: bool) -> None:
        self.calls.append(("before", [column.name for column in columns]))

    def executemany(self, _cursor, _sql: str, rows) -> None:
        self.calls.append(("executemany", [tuple(row) for row in rows]))

    def after_import(self, _cursor, _metadata, columns: list[DatabaseColumn], _keep_identity: bool) -> None:
        self.calls.append(("after", [column.name for column in columns]))


class DeltaRecordingAdapter(DatabaseAdapter):
    def __init__(self, metadata: TableMetadata) -> None:
        self.metadata = metadata
        self.calls: list[tuple[str, object]] = []

    def get_table(self, _connection, _settings, _table_name: str, schema: str | None = None) -> TableMetadata:
        return self.metadata

    def before_import(self, _cursor, _metadata, columns: list[DatabaseColumn], _keep_identity: bool) -> None:
        self.calls.append(("before", [column.name for column in columns]))

    def executemany(self, _cursor, sql: str, rows) -> None:
        operation = sql.split(None, 1)[0].lower()
        self.calls.append((operation, [tuple(row) for row in rows]))

    def after_import(self, _cursor, _metadata, columns: list[DatabaseColumn], _keep_identity: bool) -> None:
        self.calls.append(("after", [column.name for column in columns]))

    def rows_for(self, operation: str) -> list[tuple[object, ...]]:
        return [row for name, rows in self.calls if name == operation for row in rows]


class RecordingImportConnection:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> object:
        return object()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class RecordingImportAdapter(DatabaseAdapter):
    def __init__(self, metadata: TableMetadata) -> None:
        self.metadata = metadata
        self.calls: list[tuple[object, ...]] = []

    def get_table(self, _connection, _settings, _table_name: str, schema: str | None = None) -> TableMetadata:
        return self.metadata

    def truncate_table(self, _cursor, metadata: TableMetadata) -> None:
        self.calls.append(("truncate", metadata.name))

    def before_import(self, _cursor, _metadata, columns: list[DatabaseColumn], _keep_identity: bool) -> None:
        self.calls.append(("before", [column.name for column in columns]))

    def executemany(self, _cursor, sql: str, rows) -> None:
        self.calls.append(("executemany", sql, [tuple(row) for row in rows]))

    def after_import(self, _cursor, _metadata, columns: list[DatabaseColumn], _keep_identity: bool) -> None:
        self.calls.append(("after", [column.name for column in columns]))


if __name__ == "__main__":
    unittest.main()
