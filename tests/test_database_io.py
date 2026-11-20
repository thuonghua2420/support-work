from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from autocompare_tool.dbeaver_csv import DbeaverCsv, read_dbeaver_csv
from autocompare_tool.database_io import (
    DatabaseAdapter,
    DatabaseColumn,
    DatabaseConnectionSettings,
    DatabaseCsvIssue,
    DatabaseCsvSuccess,
    DatabaseCsvSummary,
    DatabaseSyncSummary,
    ForeignKeyEdge,
    OperationCancelledError,
    IMPORT_MODE_APPEND,
    IMPORT_MODE_DELETE_MATCHING_KEYS,
    IMPORT_MODE_TRUNCATE_TABLE,
    SYNC_DUPLICATE_UPSERT,
    SYNC_MODE_CONDITION,
    SYNC_MODE_INCREMENTAL,
    MySqlAdapter,
    OracleAdapter,
    PostgreSqlAdapter,
    SqlServerAdapter,
    TableMetadata,
    TableNotFoundError,
    _build_export_select_sql,
    _build_delete_by_primary_key_sql,
    _build_import_mapping,
    _build_sqlserver_connection_parts,
    _build_sync_columns,
    _build_sync_select_sql,
    _build_sync_update_sql,
    _format_csv_value,
    _format_db_value,
    _fetch_target_rows_by_keys,
    _import_one_csv,
    _parse_record_limit,
    _parse_sync_batch_size,
    _sync_one_table,
    _sqlserver_type_name,
    build_update_by_primary_key_sql,
    canonical_row_hash,
    export_csv_folder,
    export_csv_folder_multi,
    import_csv_folder,
    import_csv_folder_multi,
    normalize_database_type,
    order_tables_by_dependency,
    preferred_sqlserver_driver,
    scan_import_csv_tables,
    sync_database_tables,
    validate_connection_settings,
)


class DatabaseIoTests(unittest.TestCase):
    def test_sync_caps_old_large_batch_setting_before_workflow(self):
        from unittest.mock import Mock
        settings = DatabaseConnectionSettings(database_type="sqlserver", host=".", database="test", trusted_connection=True)
        adapter = Mock()
        with patch("autocompare_tool.database_io.get_adapter", return_value=adapter), patch("autocompare_tool.database_io._sync_one_table") as sync:
            sync_database_tables(settings, settings, table_names=["items"], batch_size=100000)
        self.assertEqual(sync.call_args.kwargs["batch_size"], 500)

    def test_cancel_before_commit_rolls_back_all_sync_modes(self):
        metadata = TableMetadata("dbo", "items", [_column("id", data_type="int", is_primary_key=True), _column("name", data_type="nvarchar")])
        settings = DatabaseConnectionSettings(database_type="sqlserver", host=".", database="test")
        for mode in ["append", "truncate_table", "incremental", "condition"]:
            with self.subTest(mode=mode):
                cancelled = False

                class CancelBeforeCommitAdapter(DeltaRecordingAdapter):
                    def truncate_table(self, *args):
                        pass

                    def after_import(self, *args):
                        nonlocal cancelled
                        cancelled = True

                def check():
                    if cancelled:
                        raise OperationCancelledError("cancel before commit")

                source, target = SyncConnection([(1, "A")]), SyncConnection([])
                with self.assertRaises(OperationCancelledError):
                    _sync_one_table(source, target, DeltaRecordingAdapter(metadata), CancelBeforeCommitAdapter(metadata),
                                    settings, settings, "items", None, True, False, DatabaseSyncSummary(), lambda _: None,
                                    sync_mode=mode, batch_size=100, where_clause="id > 0" if mode == "condition" else "",
                                    target_read_connection=SyncConnection([]), cancel=check)
                self.assertTrue(target.rolled_back)
                self.assertFalse(target.committed)

    def test_sqlserver_target_read_finishes_and_releases_locks_before_writes(self):
        metadata = TableMetadata("dbo", "customers", [_column("id", data_type="int", is_primary_key=True), _column("name", data_type="nvarchar")])
        source = SyncConnection([(1, "new"), (3, "added")])
        read = SyncConnection([(1, "old"), (2, "removed")])
        write = SyncConnection([])

        class LockCheckingAdapter(DeltaRecordingAdapter, SqlServerAdapter):
            def executemany(inner, cursor, sql, rows):
                self.assertTrue(read.rolled_back, "Read transaction must release locks before any write")
                super().executemany(cursor, sql, rows)

        adapter = LockCheckingAdapter(metadata)
        summary = DatabaseSyncSummary()
        settings = DatabaseConnectionSettings(database_type="sqlserver", host=".", database="test", schema="dbo")
        _sync_one_table(source, write, DeltaRecordingAdapter(metadata), adapter, settings, settings,
                        "customers", None, True, False, summary, lambda _: None,
                        sync_mode=SYNC_MODE_INCREMENTAL, batch_size=100, target_read_connection=read)
        self.assertEqual(summary.errors, [])
        self.assertEqual(adapter.rows_for("insert"), [(3, "added")])
        self.assertEqual(adapter.rows_for("update"), [("new", 1)])
        self.assertEqual(adapter.rows_for("delete"), [(2,)])
        self.assertTrue(write.committed)

    def test_conditional_lookup_groups_2000_composite_keys_without_losing_records(self):
        columns = [_column("tenant_id", is_primary_key=True), _column("id", is_primary_key=True), _column("name", data_type="varchar")]
        metadata = TableMetadata("dbo", "orders", columns)
        rows = [(i // 10, i, f"Name {i}") for i in range(2000)]
        connection = ConditionalSyncConnection(rows)
        adapter = DatabaseAdapter()
        with patch.object(adapter, "execute", wraps=adapter.execute) as execute:
            result = _fetch_target_rows_by_keys(adapter, connection, metadata, columns, columns[:2], [row[:2] for row in rows] + [rows[0][:2]])
        self.assertEqual(len(result), 2000)
        self.assertEqual(execute.call_count, 20)
        self.assertTrue(all(len(call.args[2]) <= 900 for call in execute.call_args_list))
        self.assertEqual(set(result.values()), set(rows))

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

    def test_sqlserver_native_client_connection_omits_encryption_keywords(self) -> None:
        parts = _build_sqlserver_connection_parts(
            DatabaseConnectionSettings(
                database_type="sqlserver",
                host="localhost",
                database="sample",
                trusted_connection=True,
                driver="SQL Server Native Client 11.0",
            )
        )

        connection_string = ";".join(parts)
        self.assertIn("DRIVER={SQL Server Native Client 11.0}", connection_string)
        self.assertIn("Trusted_Connection=yes", connection_string)
        self.assertNotIn("Encrypt=", connection_string)
        self.assertNotIn("TrustServerCertificate=", connection_string)

    def test_sqlserver_legacy_driver_connection_omits_encryption_keywords(self) -> None:
        parts = _build_sqlserver_connection_parts(
            DatabaseConnectionSettings(
                database_type="sqlserver",
                host="localhost",
                database="sample",
                trusted_connection=True,
                driver="SQL Server",
            )
        )

        connection_string = ";".join(parts)
        self.assertIn("DRIVER={SQL Server}", connection_string)
        self.assertNotIn("Encrypt=", connection_string)
        self.assertNotIn("TrustServerCertificate=", connection_string)

    def test_sqlserver_modern_odbc_connection_keeps_encryption_keywords(self) -> None:
        parts = _build_sqlserver_connection_parts(
            DatabaseConnectionSettings(
                database_type="sqlserver",
                host="localhost",
                database="sample",
                username="tester",
                password="secret",
                driver="ODBC Driver 18 for SQL Server",
                encrypt=True,
                trust_server_certificate=True,
            )
        )

        connection_string = ";".join(parts)
        self.assertIn("Encrypt=yes", connection_string)
        self.assertIn("TrustServerCertificate=yes", connection_string)
        self.assertIn("UID={tester}", connection_string)
        self.assertIn("PWD={secret}", connection_string)

    def test_sqlserver_modern_odbc_connection_defaults_encryption_off(self) -> None:
        parts = _build_sqlserver_connection_parts(
            DatabaseConnectionSettings(
                database_type="sqlserver",
                host="localhost",
                database="sample",
                trusted_connection=True,
                driver="ODBC Driver 18 for SQL Server",
            )
        )

        connection_string = ";".join(parts)
        self.assertIn("Encrypt=no", connection_string)
        self.assertIn("TrustServerCertificate=yes", connection_string)

    def test_sqlserver_preferred_driver_uses_modern_odbc_before_native_client(self) -> None:
        self.assertEqual(
            preferred_sqlserver_driver(
                [
                    "SQL Server Native Client 11.0",
                    "ODBC Driver 17 for SQL Server",
                    "ODBC Driver 18 for SQL Server",
                ]
            ),
            "ODBC Driver 18 for SQL Server",
        )

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


class ForeignKeyImportTests(unittest.TestCase):
    settings = DatabaseConnectionSettings(
        database_type="sqlserver", host=".", database="sample", schema="dbo", trusted_connection=True,
    )

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def _import(self, adapter, mode=IMPORT_MODE_APPEND, **options):
        logs = []
        with patch("autocompare_tool.database_io.get_adapter", return_value=adapter):
            summary = import_csv_folder(self.root, self.settings, existing_row_mode=mode, log=logs.append, **options)
        return summary, logs

    def _write_csvs(self, *names: str) -> None:
        for name in names:
            (self.root / f"{name}.csv").write_text("id\n1\n", encoding="utf-8")

    def test_dependency_order_handles_diamond_and_unrelated_tables(self) -> None:
        edges = [_fk("b", "z"), _fk("c", "z"), _fk("a", "b"), _fk("a", "c")]
        order, cycles = order_tables_by_dependency(["z", "e", "c", "a", "d", "b"], edges)
        self.assertEqual(order, ["d", "e", "z", "b", "c", "a"])
        self.assertEqual(cycles, [])

    def test_dependency_order_matches_case_and_schema_and_ignores_self_and_external_edges(self) -> None:
        edges = [
            _fk("Child", "PARENT"),
            _fk("parent", "Parent"),
            _fk("not-imported", "child"),
            ForeignKeyEdge("elsewhere", "parent", "dbo", "child", "FK_other_schema"),
        ]
        tables = [("DbO", "PARENT"), ("dbo", "child")]
        self.assertEqual(order_tables_by_dependency(tables, edges), (tables, []))

    def test_dependency_order_reports_only_cycle_members(self) -> None:
        edges = [_fk("b", "a"), _fk("a", "b"), _fk("c", "b"), _fk("c", "z"), _fk("e", "d"), _fk("d", "e")]
        order, cycles = order_tables_by_dependency(["z", "e", "d", "c", "B", "a"], reversed(edges))
        self.assertEqual(order, ["z", "c"])
        self.assertEqual(cycles, [["a", "B"], ["d", "e"]])

    def test_adapter_foreign_key_metadata_queries(self) -> None:
        edge = ForeignKeyEdge("dbo", "child", "dbo", "parent", "FK_test")
        for adapter, fragments in [
            (SqlServerAdapter(), ("sys.foreign_keys", "sys.foreign_key_columns")),
            (MySqlAdapter(), ("information_schema.key_column_usage", "referenced_table_name is not null")),
            (PostgreSqlAdapter(), ("pg_constraint", "contype = 'f'")),
            (OracleAdapter(), ("all_constraints", "r_constraint_name", "constraint_type = 'r'")),
        ]:
            with self.subTest(adapter=type(adapter).__name__):
                connection = Mock()
                cursor = connection.cursor.return_value
                cursor.fetchall.return_value = [("dbo", "child", "dbo", "parent", "FK_test")]
                self.assertEqual(adapter.list_foreign_keys(connection, self.settings), [edge])
                for fragment in fragments:
                    self.assertIn(fragment, cursor.execute.call_args.args[0].lower())
                if isinstance(adapter, MySqlAdapter):
                    self.assertEqual(cursor.execute.call_args.args[1], ("sample",))
                cursor.execute.assert_called_once()
                cursor.close.assert_called_once()

    def test_adapter_trigger_sql_quotes_identifiers_and_filters_enabled_triggers(self) -> None:
        metadata = TableMetadata("dbo", "items", [])
        cases = [
            (SqlServerAdapter(), [('audit]"',)], ("sys.triggers", "parent_class = 1", "OBJECT_ID(?)", "is_disabled = 0"),
             ("[dbo].[items]",), 'DISABLE TRIGGER [dbo].[audit]]"] ON [dbo].[items]',
             'ENABLE TRIGGER [dbo].[audit]]"] ON [dbo].[items]'),
            (PostgreSqlAdapter(), [('audit]"', "R")], ("pg_trigger", "%s::regclass", "NOT tgisinternal", "tgenabled <> 'D'"),
             ('"dbo"."items"',), 'ALTER TABLE ONLY "dbo"."items" DISABLE TRIGGER "audit]"""',
             'ALTER TABLE ONLY "dbo"."items" ENABLE REPLICA TRIGGER "audit]"""'),
            (OracleAdapter(), [("audit]", "Other Owner")], ("all_triggers", "table_owner = :1", "table_name = :2", "status = 'ENABLED'"),
             ("dbo", "items"), 'ALTER TRIGGER "Other Owner"."audit]" DISABLE',
             'ALTER TRIGGER "Other Owner"."audit]" ENABLE'),
        ]
        for adapter, rows, fragments, params, disable_sql, enable_sql in cases:
            with self.subTest(adapter=type(adapter).__name__):
                cursor = Mock()
                cursor.fetchall.return_value = rows
                self.assertTrue(adapter.supports_trigger_bypass)
                names = adapter.list_enabled_triggers(cursor, metadata)
                self.assertEqual(names, [rows[0][0]])
                query, bound = cursor.execute.call_args.args
                for fragment in fragments:
                    self.assertIn(fragment, query)
                self.assertEqual(bound, params[0] if isinstance(adapter, SqlServerAdapter) else params)
                adapter.disable_triggers(cursor, metadata, names)
                adapter.enable_triggers(cursor, metadata, names)
                self.assertEqual([call.args for call in cursor.execute.call_args_list[1:]], [(disable_sql,), (enable_sql,)])

    def test_trigger_bypass_is_opt_in_and_turns_off_only_catalog_results(self) -> None:
        self._write_csvs("items")
        delete = "DELETE FROM [dbo].[items] WHERE [id] = ?"
        insert = "INSERT INTO [dbo].[items] ([id]) VALUES (?)"
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                adapter = SqlServerTriggerImportAdapter(["items"], [])
                logs = []
                log_line = "Tắt trigger tạm thời trên dbo.items: audit, trace"
                adapter.trigger_names = ["audit", "trace"]

                def execute_logged_ddl(sql):
                    self.assertIn(log_line, logs)
                    adapter.execute(None, sql)

                adapter.connection.cursor.return_value.execute.side_effect = execute_logged_ddl
                with patch("autocompare_tool.database_io.get_adapter", return_value=adapter):
                    summary = import_csv_folder(
                        self.root, self.settings, existing_row_mode=IMPORT_MODE_DELETE_MATCHING_KEYS,
                        disable_triggers=enabled, log=logs.append,
                    )
                expected = [delete, insert, "commit"]
                if enabled:
                    expected = [
                        "list dbo.items", "DISABLE TRIGGER [dbo].[audit] ON [dbo].[items]",
                        "DISABLE TRIGGER [dbo].[trace] ON [dbo].[items]", delete, insert,
                        "ENABLE TRIGGER [dbo].[audit] ON [dbo].[items]",
                        "ENABLE TRIGGER [dbo].[trace] ON [dbo].[items]", "commit",
                    ]
                self.assertEqual(adapter.writes, [(sql,) for sql in expected])
                self.assertEqual(logs.count(log_line), int(enabled))
                self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("items", 1)])

    def test_trigger_cleanup_follows_failed_or_cancelled_insert(self) -> None:
        self._write_csvs("items")
        insert = "INSERT INTO [dbo].[items] ([id]) VALUES (?)"
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                adapter = SqlServerTriggerImportAdapter(["items"], [], fail_sql=None if cancelled else insert)

                def cancel():
                    if cancelled and (insert,) in adapter.writes:
                        raise OperationCancelledError()

                if cancelled:
                    with self.assertRaises(OperationCancelledError):
                        self._import(adapter, disable_triggers=True, cancel=cancel)
                else:
                    summary, _ = self._import(adapter, disable_triggers=True, cancel=cancel)
                    self.assertEqual([item.table for item in summary.failed], ["items"])
                self.assertEqual(adapter.writes, [
                    ("list dbo.items",), ("DISABLE TRIGGER [dbo].[audit] ON [dbo].[items]",),
                    (insert,), ("ENABLE TRIGGER [dbo].[audit] ON [dbo].[items]",), ("rollback",),
                ])

    def test_trigger_bypass_clears_outside_table_before_inserting(self) -> None:
        self._write_csvs("parent")
        adapter = SqlServerTriggerImportAdapter(["parent"], [_fk("outside", "parent")])
        summary, _ = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE, disable_triggers=True)
        self.assertEqual(adapter.writes, [(sql,) for sql in [
            "list dbo.outside", "DISABLE TRIGGER [dbo].[audit] ON [dbo].[outside]",
            "list dbo.parent", "DISABLE TRIGGER [dbo].[audit] ON [dbo].[parent]",
            "TRUNCATE TABLE [dbo].[outside]", "DELETE FROM [dbo].[parent]",
            "ENABLE TRIGGER [dbo].[audit] ON [dbo].[outside]", "ENABLE TRIGGER [dbo].[audit] ON [dbo].[parent]",
            "commit", "list dbo.parent", "DISABLE TRIGGER [dbo].[audit] ON [dbo].[parent]",
            "INSERT INTO [dbo].[parent] ([id]) VALUES (?)", "ENABLE TRIGGER [dbo].[audit] ON [dbo].[parent]", "commit",
        ]])
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("parent", 1)])

    def test_trigger_bypass_disable_failure_skips_table_and_continues(self) -> None:
        self._write_csvs("bad", "good")
        adapter = SqlServerTriggerImportAdapter(
            ["bad", "good"], [], fail_sql="DISABLE TRIGGER [dbo].[audit] ON [dbo].[bad]",
        )
        summary, logs = self._import(adapter, disable_triggers=True)
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("good", 1)])
        self.assertEqual(summary.failed, [DatabaseCsvIssue(
            "bad", 'Không tắt được trigger trên dbo.bad: FK driver failure. Bỏ tùy chọn "Tắt trigger" hoặc cấp quyền ALTER.',
        )])
        self.assertNotIn(("INSERT INTO [dbo].[bad] ([id]) VALUES (?)",), adapter.writes)
        self.assertLess(logs.index("Tắt trigger tạm thời trên dbo.bad: audit"),
                        next(index for index, message in enumerate(logs) if "Không tắt được trigger" in message))

    def test_clear_trigger_disable_failure_blocks_fk_parent_and_clears_unrelated_table(self) -> None:
        self._write_csvs("parent", "unrelated")
        adapter = SqlServerTriggerImportAdapter(
            ["parent", "unrelated"], [_fk("outside", "parent")],
            fail_sql="DISABLE TRIGGER [dbo].[audit] ON [dbo].[outside]",
        )
        summary, _ = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE, disable_triggers=True)
        self.assertEqual([item.table for item in summary.failed], ["dbo.outside", "parent"])
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("unrelated", 1)])
        self.assertIn(("TRUNCATE TABLE [dbo].[unrelated]",), adapter.writes)
        self.assertNotIn(("DELETE FROM [dbo].[parent]",), adapter.writes)
        self.assertNotIn(("TRUNCATE TABLE [dbo].[outside]",), adapter.writes)

    def test_trigger_enable_failure_logs_repair_sql_and_fails_table(self) -> None:
        self._write_csvs("items")
        enable = "ENABLE TRIGGER [dbo].[audit] ON [dbo].[items]"
        adapter = SqlServerTriggerImportAdapter(["items"], [], fail_sql=enable)
        adapter.trigger_names = ["audit", "trace"]
        summary, logs = self._import(adapter, disable_triggers=True)
        error = f"NGUY HIỂM: không bật lại được trigger audit trên dbo.items. Chạy thủ công: {enable};"
        self.assertEqual(summary.failed, [DatabaseCsvIssue("items", error)])
        self.assertTrue(any(error in message for message in logs))
        self.assertEqual(summary.succeeded, [])
        self.assertEqual(adapter.writes[-4:], [
            ("INSERT INTO [dbo].[items] ([id]) VALUES (?)",), (enable,),
            ("ENABLE TRIGGER [dbo].[trace] ON [dbo].[items]",), ("rollback",),
        ])

    def test_postgresql_recovers_failed_insert_transaction_before_enabling_trigger(self) -> None:
        class TriggerAdapter(TriggerImportAdapter, PostgreSqlAdapter):
            pass

        self._write_csvs("items")
        insert = 'INSERT INTO "dbo"."items" ("id") VALUES (%s)'
        adapter = TriggerAdapter(["items"], [], fail_sql=insert)
        summary, _ = self._import(adapter, disable_triggers=True)
        self.assertEqual(adapter.writes[-7:], [(sql,) for sql in [
            insert, "ROLLBACK TO SAVEPOINT autocompare_triggers", "RELEASE SAVEPOINT autocompare_triggers",
            "SAVEPOINT autocompare_triggers", 'ALTER TABLE ONLY "dbo"."items" ENABLE TRIGGER "audit"',
            "RELEASE SAVEPOINT autocompare_triggers", "rollback",
        ]])
        self.assertEqual([item.table for item in summary.failed], ["items"])

    def test_oracle_clear_rolls_back_before_enabling_triggers_after_failure(self) -> None:
        class TriggerAdapter(TriggerImportAdapter, OracleAdapter):
            pass

        self._write_csvs("parent")
        adapter = TriggerAdapter(["parent"], [_fk("outside", "parent")], fail_sql='DELETE FROM "dbo"."parent"')
        summary, logs = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE, disable_triggers=True)
        self.assertEqual(adapter.writes[-6:], [(sql,) for sql in [
            'DELETE FROM "dbo"."outside"', 'DELETE FROM "dbo"."parent"', "rollback",
            'ALTER TRIGGER "dbo"."audit" ENABLE', 'ALTER TRIGGER "dbo"."audit" ENABLE', "rollback",
        ]])
        self.assertEqual([item.table for item in summary.failed], ["dbo.outside", "parent"])
        self.assertIn("Tắt trigger tạm thời trên dbo.outside: audit (DDL Oracle tự động commit)", logs)

    def test_oracle_partial_disable_failure_restores_only_disabled_triggers(self) -> None:
        class TriggerAdapter(TriggerImportAdapter, OracleAdapter):
            pass

        self._write_csvs("items")
        adapter = TriggerAdapter(["items"], [], fail_sql='ALTER TRIGGER "dbo"."trace" DISABLE')
        adapter.trigger_names = ["audit", "trace"]
        summary, _ = self._import(adapter, disable_triggers=True)
        self.assertEqual(adapter.writes, [(sql,) for sql in [
            "list dbo.items", 'ALTER TRIGGER "dbo"."audit" DISABLE', 'ALTER TRIGGER "dbo"."trace" DISABLE',
            'ALTER TRIGGER "dbo"."audit" ENABLE', "rollback",
        ]])
        self.assertEqual([item.table for item in summary.failed], ["items"])

    def test_unsupported_trigger_bypass_warns_once_and_imports(self) -> None:
        self._write_csvs("first", "second")
        adapter = FolderImportAdapter(["first", "second"], [])
        settings = DatabaseConnectionSettings(database_type="mysql", host=".", database="sample", username="tester")
        logs = []
        with patch("autocompare_tool.database_io.get_adapter", return_value=adapter):
            summary = import_csv_folder(self.root, settings, disable_triggers=True, log=logs.append)
        self.assertFalse(MySqlAdapter.supports_trigger_bypass)
        self.assertEqual(logs.count("Không hỗ trợ tắt trigger trên MySQL; import tiếp tục với trigger đang bật."), 1)
        self.assertEqual(summary.csv_count, 2)
        self.assertEqual(summary.errors, [])

    def test_all_import_modes_insert_parents_first(self) -> None:
        self._write_csvs("a_child", "z_parent")
        for mode in (IMPORT_MODE_APPEND, IMPORT_MODE_DELETE_MATCHING_KEYS, IMPORT_MODE_TRUNCATE_TABLE):
            with self.subTest(mode=mode):
                adapter = FolderImportAdapter(["a_child", "z_parent"], [_fk("a_child", "z_parent")])
                summary, _ = self._import(adapter, mode)
                self.assertEqual(adapter.calls.count(("foreign_keys",)), 1)
                self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("z_parent", 1), DatabaseCsvSuccess("a_child", 1)])
                self.assertEqual(summary.errors, [])
                if mode == IMPORT_MODE_DELETE_MATCHING_KEYS:
                    self.assertEqual(adapter.writes, [
                        ('DELETE FROM "dbo"."z_parent" WHERE "id" = ?',), ('INSERT INTO "dbo"."z_parent" ("id") VALUES (?)',),
                        ("commit",),
                        ('DELETE FROM "dbo"."a_child" WHERE "id" = ?',), ('INSERT INTO "dbo"."a_child" ("id") VALUES (?)',),
                        ("commit",),
                    ])

    def test_truncate_clears_transitive_children_once_before_inserts(self) -> None:
        self._write_csvs("z_parent", "a_child")
        adapter = FolderImportAdapter(["a_child", "z_parent"], [
            _fk("a_child", "z_parent"),
            _fk("outside", "a_child"),
            ForeignKeyEdge("other", "grandchild", "dbo", "outside", "FK_grandchild"),
        ])
        summary, logs = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE)

        self.assertEqual(adapter.writes, [
            ('TRUNCATE TABLE "other"."grandchild"',),
            ('DELETE FROM "dbo"."outside"',),
            ('DELETE FROM "dbo"."a_child"',),
            ('DELETE FROM "dbo"."z_parent"',),
            ("commit",),
            ('INSERT INTO "dbo"."z_parent" ("id") VALUES (?)',),
            ("commit",),
            ('INSERT INTO "dbo"."a_child" ("id") VALUES (?)',),
            ("commit",),
        ])
        self.assertEqual(summary.csv_count, 2)
        self.assertEqual(summary.errors, [])
        self.assertIn("Thứ tự xóa dữ liệu: " + " → ".join(sql for (sql,) in adapter.writes[:4]), logs)
        self.assertIn('Xóa thêm table ngoài folder CSV: "dbo"."outside"', logs)
        self.assertIn('Xóa thêm table ngoài folder CSV: "other"."grandchild"', logs)

    def test_truncate_rolls_back_and_reports_all_affected_tables_on_failure(self) -> None:
        self._write_csvs("parent")
        adapter = FolderImportAdapter(["parent"], [_fk("outside", "parent")], fail_sql='DELETE FROM "dbo"."parent"')
        summary, _ = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE)
        self.assertEqual(adapter.writes, [
            ('TRUNCATE TABLE "dbo"."outside"',), ('DELETE FROM "dbo"."parent"',), ("rollback",),
        ])
        self.assertEqual([item.table for item in summary.failed], ["dbo.outside", "parent"])
        self.assertTrue(all("FK driver failure" in item.message for item in summary.failed))
        self.assertEqual(summary.csv_count, 0)

    def test_truncate_cancellation_rolls_back_before_insert(self) -> None:
        self._write_csvs("parent")
        adapter = FolderImportAdapter(["parent"], [_fk("outside", "parent")])

        def cancel() -> None:
            if adapter.writes:
                raise OperationCancelledError("cancelled during clear")

        with self.assertRaisesRegex(OperationCancelledError, "cancelled during clear"):
            self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE, cancel=cancel)
        self.assertEqual(adapter.writes, [('TRUNCATE TABLE "dbo"."outside"',), ("rollback",)])
        self.assertTrue(adapter.connection.closed)

    def test_truncate_excludes_invalid_csv_roots_and_clears_unselected_children(self) -> None:
        self._write_csvs("parent", "unselected")
        (self.root / "bad.csv").write_text("unknown\n1\n", encoding="utf-8")
        adapter = FolderImportAdapter(["parent", "unselected", "bad"], [
            _fk("unselected", "parent"), _fk("outside", "bad"),
        ])
        summary, logs = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE, table_names=["parent", "bad"])
        clears = [sql for (sql,) in adapter.writes if sql.startswith(("DELETE FROM", "TRUNCATE TABLE"))]
        self.assertEqual(clears, ['TRUNCATE TABLE "dbo"."unselected"', 'DELETE FROM "dbo"."parent"'])
        self.assertIn('Xóa thêm table ngoài tập CSV nhập: "dbo"."unselected"', logs)
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("parent", 1)])
        self.assertEqual([item.table for item in summary.failed], ["bad"])

    def test_truncate_uses_rollbackable_delete_when_truncate_auto_commits(self) -> None:
        self._write_csvs("parent")
        adapter = FolderImportAdapter(["parent"], [_fk("outside", "parent")])
        adapter.transactional_truncate = False
        summary, _ = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE)
        self.assertEqual(adapter.writes[:3], [
            ('DELETE FROM "dbo"."outside"',), ('DELETE FROM "dbo"."parent"',), ("commit",),
        ])
        self.assertFalse(summary.failed)

    def test_mysql_rejects_nontransactional_tables_before_clearing(self) -> None:
        cursor = Mock()
        cursor.fetchall.return_value = [("parent",)]
        adapter = MySqlAdapter()
        tables = [TableMetadata("sample", "parent", []), TableMetadata("sample", "outside", [])]
        with self.assertRaisesRegex(ValueError, r"sample\.outside"):
            adapter.validate_import_clear(cursor, tables)
        cursor.execute.assert_called_once()
        self.assertIn("e.TRANSACTIONS = 'YES'", cursor.execute.call_args.args[0])

    def test_empty_or_failed_foreign_key_lookup_keeps_per_csv_truncate(self) -> None:
        self._write_csvs("a_child", "z_parent")
        for edges in ([], RuntimeError("no catalog access")):
            with self.subTest(edges=edges):
                adapter = FolderImportAdapter(["a_child", "z_parent"], edges)
                summary, logs = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE)
                prefix = [("rollback",)] if isinstance(edges, Exception) else []
                self.assertEqual(adapter.writes, prefix + [
                    ('TRUNCATE TABLE "dbo"."a_child"',), ('INSERT INTO "dbo"."a_child" ("id") VALUES (?)',),
                    ("commit",),
                    ('TRUNCATE TABLE "dbo"."z_parent"',), ('INSERT INTO "dbo"."z_parent" ("id") VALUES (?)',),
                    ("commit",),
                ])
                self.assertEqual(summary.csv_count, 2)
                self.assertEqual("Không đọc được khóa ngoại: no catalog access" in logs, bool(prefix))

    def test_append_warns_and_imports_cycle_members_last_in_name_order(self) -> None:
        self._write_csvs("a", "b", "c", "d", "e", "z")
        adapter = FolderImportAdapter(["a", "b", "c", "d", "e", "z"], [
            _fk("a", "d"), _fk("d", "a"), _fk("b", "e"), _fk("e", "b"), _fk("c", "z"),
        ])
        summary, logs = self._import(adapter)
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess(name, 1) for name in ("z", "c", "a", "b", "d", "e")])
        self.assertEqual(summary.failed, [])
        self.assertIn("Cảnh báo: chu trình khóa ngoại giữa dbo.a, dbo.d; import theo thứ tự tên", logs)
        self.assertIn("Cảnh báo: chu trình khóa ngoại giữa dbo.b, dbo.e; import theo thứ tự tên", logs)

    def test_delete_matching_keys_attempts_cycle_members_and_reports_insert_failure(self) -> None:
        self._write_csvs("a", "b", "c")
        failed_insert = 'INSERT INTO "dbo"."a" ("id") VALUES (?)'
        adapter = FolderImportAdapter(["a", "b", "c"], [_fk("a", "b"), _fk("b", "a")], fail_sql=failed_insert)
        summary, logs = self._import(adapter, IMPORT_MODE_DELETE_MATCHING_KEYS)
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("c", 1), DatabaseCsvSuccess("b", 1)])
        self.assertEqual(summary.failed, [DatabaseCsvIssue("a", "FK driver failure")])
        self.assertIn("Cảnh báo: chu trình khóa ngoại giữa dbo.a, dbo.b; import theo thứ tự tên", logs)
        self.assertEqual(adapter.writes, [
            ('DELETE FROM "dbo"."c" WHERE "id" = ?',),
            ('INSERT INTO "dbo"."c" ("id") VALUES (?)',),
            ("commit",),
            ('DELETE FROM "dbo"."a" WHERE "id" = ?',),
            (failed_insert,),
            ("rollback",),
            ('DELETE FROM "dbo"."b" WHERE "id" = ?',),
            ('INSERT INTO "dbo"."b" ("id") VALUES (?)',),
            ("commit",),
        ])

    def test_truncate_keeps_cycle_and_its_parent_and_clears_independent_table(self) -> None:
        self._write_csvs("parent", "independent")
        adapter = FolderImportAdapter(["parent", "independent"], [
            _fk("a", "parent"), _fk("b", "a"), _fk("a", "b"), _fk("unused", "parent"),
        ])
        summary, _ = self._import(adapter, IMPORT_MODE_TRUNCATE_TABLE)
        self.assertEqual(adapter.writes, [
            ('TRUNCATE TABLE "dbo"."independent"',), ("commit",),
            ('INSERT INTO "dbo"."independent" ("id") VALUES (?)',), ("commit",),
        ])
        self.assertEqual([item.table for item in summary.failed], ["dbo.a", "dbo.b", "parent"])
        self.assertTrue(all("dbo.a, dbo.b" in item.message for item in summary.failed))

    def test_insert_failure_rolls_back_one_csv_and_import_continues(self) -> None:
        self._write_csvs("parent", "child")
        adapter = FolderImportAdapter(["parent", "child"], [_fk("child", "parent")],
                                      fail_sql='DELETE FROM "dbo"."parent" WHERE "id" = ?')
        summary, _ = self._import(adapter, IMPORT_MODE_DELETE_MATCHING_KEYS)
        self.assertEqual(summary.failed, [DatabaseCsvIssue("parent", "FK driver failure")])
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("child", 1)])
        self.assertEqual(adapter.writes[1], ("rollback",))
        self.assertEqual(adapter.writes[-1], ("commit",))

    def test_import_report_and_preflight_include_only_importable_tables_in_ordering(self) -> None:
        self._write_csvs("items", "missing", "generated")
        (self.root / "empty.csv").write_text("", encoding="utf-8")
        (self.root / "bad.csv").write_text("unknown\n1\n", encoding="utf-8")
        adapter = FolderImportAdapter(["Items", "generated", "bad"], [_fk("outside", "bad")])
        adapter.tables["generated"] = TableMetadata("dbo", "generated", [_column("id", is_computed=True)])
        summary, logs = self._import(adapter)

        self.assertNotIn(("foreign_keys",), adapter.calls)
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("items", 1)])
        self.assertEqual([item.table for item in summary.failed], ["bad"])
        self.assertEqual(summary.skipped_items, [
            DatabaseCsvIssue("empty", "bỏ qua CSV rỗng"),
            DatabaseCsvIssue("generated", "bỏ qua vì không có column nào có thể nhập"),
            DatabaseCsvIssue("missing", "bỏ qua vì không tìm thấy table: dbo.missing"),
        ])
        self.assertEqual(summary.skipped[0], "empty.csv -> bỏ qua CSV rỗng")
        self.assertEqual(logs[-6:], [
            "===== Tổng kết =====",
            "Thành công (1): items (1 dòng)",
            f"Lỗi (1): bad — {summary.failed[0].message}",
            "Bỏ qua (3): empty — bỏ qua CSV rỗng",
            "  generated — bỏ qua vì không có column nào có thể nhập",
            "  missing — bỏ qua vì không tìm thấy table: dbo.missing",
        ])

    def test_export_report_preserves_legacy_results_and_lists_each_issue(self) -> None:
        connection = Mock()
        connection.cursor.return_value.fetchmany.side_effect = [[(1,)], []]
        adapter = FolderImportAdapter(["Items"], [])
        adapter.connect = Mock(return_value=connection)
        adapter.tables["empty"] = TableMetadata("dbo", "empty", [])
        adapter.tables["blank"] = TableMetadata("dbo", "blank", [])
        logs = []
        with patch("autocompare_tool.database_io.get_adapter", return_value=adapter):
            summary = export_csv_folder(self.root, self.settings, ["dbo.items", "missing", "gone", "empty", "blank"], logs.append)

        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("Items", 1)])
        self.assertEqual(summary.failed, [DatabaseCsvIssue("missing", "missing"), DatabaseCsvIssue("gone", "gone")])
        self.assertEqual(summary.skipped_items, [
            DatabaseCsvIssue("empty", "bỏ qua vì không có column xuất"),
            DatabaseCsvIssue("blank", "bỏ qua vì không có column xuất"),
        ])
        self.assertEqual(summary.errors[0], f"LỖI {self.root.resolve() / 'missing.csv'}: missing")
        self.assertEqual(summary.skipped[0], "empty -> bỏ qua vì không có column xuất")
        self.assertEqual(logs[-6:], [
            "===== Tổng kết =====",
            "Thành công (1): Items (1 dòng)",
            "Lỗi (2): missing — missing",
            "  gone — gone",
            "Bỏ qua (2): empty — bỏ qua vì không có column xuất",
            "  blank — bỏ qua vì không có column xuất",
        ])

    def test_export_with_no_tables_still_logs_report(self) -> None:
        adapter = FolderImportAdapter([], [])
        adapter.list_tables = Mock(return_value=[])
        logs = []
        with patch("autocompare_tool.database_io.get_adapter", return_value=adapter):
            summary = export_csv_folder(self.root, self.settings, log=logs.append)
        self.assertEqual(summary.skipped, ["Không tìm thấy table để xuất."])
        self.assertEqual(logs[-4:], [
            "===== Tổng kết =====", "Thành công (0)", "Lỗi (0)", "Bỏ qua (1): Không tìm thấy table để xuất.",
        ])


class MultiDatabaseCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.settings = ForeignKeyImportTests.settings
        self.logs = []

    def _import(self, adapters, **options):
        return import_csv_folder_multi(
            self.root, self._connections(adapters), log=self.logs.append, **options,
        )

    def _connections(self, adapters):
        return [(f"db{index}", replace(self.settings, database=f"db{index}"))
                for index in range(1, len(adapters) + 1)]

    def _write_csvs(self, *names):
        for name in names:
            (self.root / f"{name}.csv").write_text("id\n1\n", encoding="utf-8")

    def test_import_inserts_into_every_matching_database_and_aggregates_missing_tables(self):
        self._write_csvs("items", "missing")
        first = FolderImportAdapter(["items"], [])
        failed = FolderImportAdapter([], [])
        failed.connect = Mock(side_effect=RuntimeError("driver error\nconnection refused"))
        unaffected = FolderImportAdapter([], [])
        last = FolderImportAdapter(["items"], [])
        adapters = [first, failed, unaffected, last]

        with patch("autocompare_tool.database_io.get_adapter", side_effect=adapters):
            summary = self._import(adapters, table_names=(name for name in ["items", "missing"]))

        self.assertEqual((summary.csv_count, summary.row_count, summary.error_count), (2, 2, 1))
        self.assertEqual(summary.succeeded, [
            DatabaseCsvSuccess("db1: items", 1, "db1"), DatabaseCsvSuccess("db4: items", 1, "db4"),
        ])
        self.assertEqual(summary.failed, [
            DatabaseCsvIssue("db2: <kết nối>", "driver error\nconnection refused", "db2"),
        ])
        self.assertEqual(summary.skipped_items, [
            DatabaseCsvIssue("missing", "Không tìm thấy table trong database đã chọn"),
        ])
        self.assertEqual(unaffected.writes, [])
        for adapter in (first, last):
            self.assertEqual(adapter.writes, [('INSERT INTO "dbo"."items" ("id") VALUES (?)',), ("commit",)])
        self.assertTrue(all(adapter.connection.closed for adapter in (first, unaffected, last)))
        overall = self.logs.index("===== Tổng kết tất cả database =====")
        self.assertTrue(all(line.startswith(("[db1] ", "[db2] ", "[db3] ", "[db4] "))
                            for line in self.logs[:overall]))
        self.assertEqual(self.logs.count("===== Tổng kết tất cả database ====="), 1)
        self.assertIn("[db2] connection refused", self.logs[:overall])
        self.assertIn("Tổng cộng: 2 file CSV, 2 dòng, bỏ qua 1 mục, lỗi 1 mục.", self.logs[overall:])
        self.assertIn("[db2] <kết nối> — driver error", self.logs[overall:])
        self.assertIn("missing — Không tìm thấy table trong database đã chọn", self.logs[overall:])

    def test_import_applies_existing_row_mode_and_trigger_bypass_to_every_database(self):
        self._write_csvs("items")
        for mode, statement in (
            (IMPORT_MODE_TRUNCATE_TABLE, "TRUNCATE TABLE [dbo].[items]"),
            (IMPORT_MODE_DELETE_MATCHING_KEYS, "DELETE FROM [dbo].[items] WHERE [id] = ?"),
        ):
            with self.subTest(mode=mode):
                adapters = [SqlServerTriggerImportAdapter(["items"], []) for _ in range(2)]
                with patch("autocompare_tool.database_io.get_adapter", side_effect=adapters):
                    summary = self._import(adapters, existing_row_mode=mode, disable_triggers=True, keep_identity=True)
                self.assertEqual(summary.csv_count, 2)
                for adapter in adapters:
                    self.assertEqual(adapter.writes, [(sql,) for sql in [
                        "list dbo.items", "DISABLE TRIGGER [dbo].[audit] ON [dbo].[items]", statement,
                        "INSERT INTO [dbo].[items] ([id]) VALUES (?)", "ENABLE TRIGGER [dbo].[audit] ON [dbo].[items]",
                        "commit",
                    ]])

    def test_import_cancels_inside_and_between_databases(self):
        self._write_csvs("items")
        for cancel_after in (('INSERT INTO "dbo"."items" ("id") VALUES (?)',), ("commit",)):
            with self.subTest(cancel_after=cancel_after):
                first = FolderImportAdapter(["items"], [])
                last = FolderImportAdapter(["items"], [])
                last.connect = Mock(return_value=last.connection)

                def cancel():
                    if cancel_after in first.writes:
                        raise OperationCancelledError()

                with patch("autocompare_tool.database_io.get_adapter", side_effect=[first, last]):
                    with self.assertRaises(OperationCancelledError):
                        self._import([first, last], cancel=cancel)
                self.assertTrue(first.connection.closed)
                self.assertEqual(first.connection.rolled_back, cancel_after != ("commit",))
                last.connect.assert_not_called()

    def _export_adapter(self, tables, value):
        adapter = FolderImportAdapter(tables, [])
        cursor = Mock()
        adapter.connection.cursor = Mock(return_value=cursor)
        adapter.execute = Mock(side_effect=lambda *_: setattr(cursor.fetchmany, "side_effect", [[(value,)], []]))
        adapter.list_tables = Mock(return_value=tables)
        return adapter

    def test_export_filters_tables_and_keeps_the_first_export_on_both_kinds_of_collision(self):
        first = self._export_adapter(["Items", "first_only", "unrequested"], 1)
        last = self._export_adapter(["items", "second_only", "unrequested"], 2)
        last.tables["alias"] = TableMetadata("dbo", "dbo.items", [_column("id")])
        adapters = [first, last]
        with patch("autocompare_tool.database_io.get_adapter", side_effect=adapters):
            summary = export_csv_folder_multi(
                self.root, self._connections(adapters), ["dbo.items", "first_only", "second_only", "alias", "missing"],
                self.logs.append,
            )

        self.assertEqual(sorted(path.name for path in self.root.iterdir()), [
            "dbo.Items.csv", "first_only.csv", "second_only.csv",
        ])
        self.assertEqual((self.root / "dbo.Items.csv").read_bytes(), b"id\r\n1\r\n")
        self.assertEqual((self.root / "second_only.csv").read_bytes(), b"id\r\n2\r\n")
        self.assertEqual((summary.csv_count, summary.row_count, summary.error_count), (3, 3, 0))
        self.assertEqual(summary.skipped_items, [
            DatabaseCsvIssue("db2: items", "trùng tên với table đã xuất từ db1", "db2"),
            DatabaseCsvIssue("db2: dbo.items", "trùng tên với table đã xuất từ db1", "db2"),
            DatabaseCsvIssue("missing", "Không tìm thấy table trong database đã chọn"),
        ])

    def test_export_list_failure_closes_connection_and_continues(self):
        failed = self._export_adapter([], 1)
        failed.list_tables.side_effect = RuntimeError("list driver error")
        last = self._export_adapter(["items"], 2)
        adapters = [failed, last]
        with patch("autocompare_tool.database_io.get_adapter", side_effect=adapters):
            summary = export_csv_folder_multi(self.root, self._connections(adapters), log=self.logs.append)

        self.assertEqual(summary.failed, [DatabaseCsvIssue("db1: <kết nối>", "list driver error", "db1")])
        self.assertEqual(summary.succeeded, [DatabaseCsvSuccess("db2: items", 1, "db2")])
        self.assertTrue(failed.connection.closed and last.connection.closed)

    def test_export_cancellation_during_fetch_closes_connection_and_stops(self):
        first = self._export_adapter(["items"], 1)
        last = self._export_adapter(["items"], 2)
        last.connect = Mock(return_value=last.connection)
        adapters = [first, last]

        def cancel():
            if first.connection.cursor.return_value.fetchmany.called:
                raise OperationCancelledError()

        with patch("autocompare_tool.database_io.get_adapter", side_effect=adapters):
            with self.assertRaises(OperationCancelledError):
                export_csv_folder_multi(self.root, self._connections(adapters), cancel=cancel)

        self.assertTrue(first.connection.closed)
        last.connect.assert_not_called()


def _fk(child: str, parent: str) -> ForeignKeyEdge:
    return ForeignKeyEdge("dbo", child, "dbo", parent, f"FK_{child}_{parent}")


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
            group_count = sql.count(" OR ") + 1
            key_size = len(params) // group_count
            keys = {params[i:i + key_size] for i in range(0, len(params), key_size)}
            self.rows = [row for row in self.source_rows if row[:key_size] in keys]
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
    def __init__(self, calls=None) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.calls = calls if calls is not None else []

    def cursor(self) -> object:
        return object()

    def commit(self) -> None:
        self.committed = True
        self.calls.append(("commit",))

    def rollback(self) -> None:
        self.rolled_back = True
        self.calls.append(("rollback",))

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


class FolderImportAdapter(RecordingImportAdapter):
    def __init__(self, tables, edges, fail_sql=None) -> None:
        super().__init__(TableMetadata("dbo", "", []))
        self.tables = {table.casefold(): TableMetadata("dbo", table, [_column("id", is_primary_key=True)])
                       for table in tables}
        self.edges = edges
        self.fail_sql = fail_sql
        self.writes = []
        self.connection = RecordingImportConnection(self.writes)

    def connect(self, settings):
        return self.connection

    def get_table(self, _connection, _settings, table_name, schema=None):
        try:
            return self.tables[table_name.casefold()]
        except KeyError:
            raise TableNotFoundError(table_name) from None

    def list_foreign_keys(self, connection, settings):
        self.calls.append(("foreign_keys",))
        if isinstance(self.edges, Exception):
            raise self.edges
        return self.edges

    def truncate_table(self, cursor, metadata) -> None:
        DatabaseAdapter.truncate_table(self, cursor, metadata)

    def execute(self, cursor, sql, params=()) -> None:
        self.writes.append((sql,))
        if sql == self.fail_sql:
            raise RuntimeError("FK driver failure")

    def executemany(self, cursor, sql, rows) -> None:
        self.execute(cursor, sql)


class TriggerImportAdapter(FolderImportAdapter):
    def __init__(self, tables, edges, fail_sql=None) -> None:
        super().__init__(tables, edges, fail_sql)
        self.trigger_names = ["audit"]
        self.connection.cursor = Mock()
        self.connection.cursor.return_value.execute.side_effect = lambda sql: self.execute(None, sql)

    def list_enabled_triggers(self, cursor, metadata):
        self.writes.append((f"list {metadata.schema}.{metadata.name}",))
        return self.trigger_names


class SqlServerTriggerImportAdapter(TriggerImportAdapter, SqlServerAdapter):
    pass


if __name__ == "__main__":
    unittest.main()
