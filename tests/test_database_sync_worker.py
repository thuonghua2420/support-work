from __future__ import annotations

import multiprocessing
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from autocompare_tool.database_io import DatabaseSyncSummary, OperationCancelledError
from autocompare_tool.database_sync_worker import ObservedConnection, _run_worker, run_sync_isolated
from autocompare_tool.web_app import CancelToken, JobManager


def successful_worker(sender, args, kwargs):
    sender.send(("activity", "commit"))
    sender.send(("log", "done"))
    sender.send(("result", DatabaseSyncSummary()))
    sender.close()


def blocked_worker(sender, args, kwargs):
    sender.send(("activity", args[0]))
    sender.send(("log", "blocked"))
    # Represents a native call that never returns, with no safe checkpoints.
    time.sleep(60)


def failed_worker(sender, args, kwargs):
    sender.send(("error", "simulated driver error"))
    sender.close()


def transaction_worker(sender, args, kwargs):
    connection = sqlite3.connect(args[0])
    connection.executemany("INSERT INTO items VALUES (?)", [(i,) for i in range(2000)])
    sender.send(("activity", "uncommitted batch"))
    sender.send(("log", "blocked"))
    time.sleep(60)


class SyncWorkerTests(unittest.TestCase):
    def test_killed_local_transaction_is_rolled_back_and_lock_released(self):
        # Local SQLite fixture, never a user's SQL Server. Demonstrates process
        # teardown without relying on a Python finally/rollback in the worker.
        with tempfile.TemporaryDirectory() as folder:
            path = folder + "/cancel.db"
            connection = sqlite3.connect(path, timeout=1)
            try:
                connection.execute("CREATE TABLE items (id INTEGER)")
                connection.commit()
                token = CancelToken()
                with self.assertRaises(OperationCancelledError):
                    _run_worker(transaction_worker, (path,), {}, lambda m: token.cancel() if m == "blocked" else None, token.throw_if_cancelled, 10)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0], 0)
                connection.execute("INSERT INTO items VALUES (9999)")
                connection.commit()
            finally:
                connection.close()

    def test_production_worker_propagates_validation_error_without_connecting(self):
        from autocompare_tool.database_io import DatabaseConnectionSettings
        settings = DatabaseConnectionSettings(database_type="invalid", host="", database="")
        with self.assertRaises(RuntimeError):
            run_sync_isolated(settings, settings)
        self.assertFalse(multiprocessing.active_children())

    def test_result_and_logs_return_only_after_process_exits(self):
        before = {p.pid for p in multiprocessing.active_children()}
        logs = []
        result = _run_worker(successful_worker, (), {}, logs.append, None, 10)
        self.assertIsInstance(result, DatabaseSyncSummary)
        self.assertIn("done", logs)
        self.assertEqual(before, {p.pid for p in multiprocessing.active_children()})

    def test_cancel_during_each_blocking_phase_without_safe_checkpoint(self):
        for stage in ["connect", "execute", "fetchmany", "executemany", "commit", "rollback"]:
            with self.subTest(stage=stage):
                token = CancelToken()
                requested = []

                def log(message):
                    if message == "blocked":
                        requested.append(time.monotonic())
                        token.cancel()

                with self.assertRaisesRegex(OperationCancelledError, "commit"):
                    _run_worker(blocked_worker, (stage,), {}, log, token.throw_if_cancelled, 10)
                self.assertLess(time.monotonic() - requested[0], 3)
                self.assertFalse(multiprocessing.active_children())

    def test_timeout_stops_blocked_driver_and_reports_stage(self):
        with self.assertRaisesRegex(TimeoutError, "executemany"):
            _run_worker(blocked_worker, ("executemany",), {}, lambda _: None, None, 2)
        self.assertFalse(multiprocessing.active_children())

    def test_error_does_not_leak_worker(self):
        with self.assertRaisesRegex(RuntimeError, "simulated driver error"):
            _run_worker(failed_worker, (), {}, lambda _: None, None, 10)
        self.assertFalse(multiprocessing.active_children())

    def test_pre_cancel_does_not_spawn(self):
        token = CancelToken()
        token.cancel()
        with self.assertRaises(OperationCancelledError):
            _run_worker(blocked_worker, (), {}, lambda _: None, token.throw_if_cancelled, 10)
        self.assertFalse(multiprocessing.active_children())

    def test_timeout_validation(self):
        for value in [0, 9, 3601, "bad", None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_sync_isolated(step_timeout=value)

    def test_job_manager_remains_responsive_while_driver_is_blocked(self):
        manager = JobManager()
        ready = threading.Event()

        def operation(log, token):
            def relay(message):
                log(message)
                if message == "blocked":
                    ready.set()
            return _run_worker(blocked_worker, ("executemany",), {}, relay, token.throw_if_cancelled, 10)

        job = manager.start("db_sync", "sync", operation)
        self.assertTrue(ready.wait(10))
        with self.assertRaises(RuntimeError):
            manager.start("db_sync", "second writer", operation)
        with self.assertRaises(ValueError):
            manager.cancel_current("other-job")
        started = time.monotonic()
        self.assertTrue(manager.cancel_current(job.id)["cancel_requested"])
        self.assertLess(time.monotonic() - started, 0.5)
        deadline = time.monotonic() + 5
        while manager.snapshot()["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(manager.snapshot()["state"], "cancelled")
        self.assertFalse(multiprocessing.active_children())

    def test_observer_tracks_calls_without_sql_or_credentials_and_enables_batch(self):
        raw = Mock()
        raw_cursor = raw.cursor.return_value
        raw_cursor.execute.return_value = raw_cursor
        stages = []
        connection = ObservedConnection(raw, stages.append, "target", fast_batch=True)
        cursor = connection.cursor()
        self.assertTrue(raw_cursor.fast_executemany)
        self.assertIs(cursor.execute("secret SQL", ["password"]), cursor)
        cursor.fetchmany(500)
        connection.commit()
        self.assertIn("target: fetchmany", stages)
        self.assertIn("target: đã commit", stages)
        self.assertNotIn("secret", " ".join(stages))


if __name__ == "__main__":
    unittest.main()
