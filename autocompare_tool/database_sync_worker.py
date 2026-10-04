"""Isolate native DB drivers from the HTTP server; never terminate a Python thread.

Each run owns its process, DB sessions and IPC pipe. A killed pipe is discarded,
never reused. The receiver is separate so a partial IPC message cannot block cancel.
"""
from __future__ import annotations

import multiprocessing
import queue
import threading
import time

from .database_io import OperationCancelledError, sync_database_tables

DEFAULT_SYNC_TIMEOUT = 120
INTERRUPTED_SYNC_WARNING = (
    "Đã ngắt tiến trình đồng bộ và các kết nối do tiến trình này sở hữu. "
    "CSDL có thể còn rollback giao dịch chưa commit; các table đã commit vẫn được giữ. "
    "Nếu ngắt đúng lúc commit, cần kiểm tra dữ liệu đích trước khi chạy lại. "
    "TRUNCATE/DDL trên CSDL tự commit không thể hoàn tác bằng nút Hủy."
)


def _sync_worker(sender, args, kwargs):
    try:
        result = sync_database_tables(
            *args, **kwargs,
            log=lambda message: sender.send(("log", str(message))),
            activity=lambda stage: sender.send(("activity", stage)),
        )
        sender.send(("result", result))
    except Exception as exc:
        sender.send(("error", str(exc)))
    finally:
        sender.close()


def _receive_messages(receiver, inbox, stopped):
    try:
        while not stopped.is_set():
            message = receiver.recv()
            while not stopped.is_set():
                try:
                    inbox.put(message, timeout=0.1)
                    break
                except queue.Full:
                    pass
    except (EOFError, OSError):
        pass
    finally:
        receiver.close()


def run_sync_isolated(*args, log=None, cancel=None, step_timeout=DEFAULT_SYNC_TIMEOUT, **kwargs):
    """Return only after the worker exits; cancellation does not wait for DB calls."""
    try:
        timeout = int(step_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("Thời gian chờ đồng bộ phải là số giây từ 10 đến 3600.") from exc
    if not 10 <= timeout <= 3600:
        raise ValueError("Thời gian chờ đồng bộ phải từ 10 đến 3600 giây.")
    return _run_worker(_sync_worker, args, kwargs, log or (lambda _: None), cancel, timeout)


def _run_worker(target, args, kwargs, log, cancel, timeout, *, task_name="Đồng bộ", interrupted_warning=INTERRUPTED_SYNC_WARNING):
    if cancel:
        cancel()
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=target, args=(sender, args, kwargs), daemon=True)
    inbox = queue.Queue(maxsize=128)
    stopped = threading.Event()
    reader = threading.Thread(target=_receive_messages, args=(receiver, inbox, stopped), daemon=True)
    started = False
    try:
        worker.start()
        started = True
        sender.close()
        reader.start()
        last_activity = time.monotonic()
        next_wait_notice = last_activity + 10
        stage = "khởi tạo tác vụ"
        result = None
        completed = False
        log(f"{task_name} chạy trong tiến trình riêng. Hủy sẽ ngắt tiến trình, không chờ bước đang chạy kết thúc.")
        while True:
            if cancel:
                cancel()
            try:
                kind, value = inbox.get(timeout=0.1)
            except queue.Empty:
                if not worker.is_alive() and not reader.is_alive() and inbox.empty():
                    if completed and worker.exitcode == 0:
                        return result
                    raise RuntimeError(f"{task_name}: tiến trình kết thúc bất thường (mã {worker.exitcode}). {interrupted_warning}")
            else:
                # Logs are not a heartbeat: only real workflow/DB progress resets
                # the deadline, so a blocked native call cannot live indefinitely.
                if kind == "activity":
                    last_activity = time.monotonic()
                    next_wait_notice = last_activity + 10
                    stage = value
                elif kind == "log":
                    log(value)
                elif kind == "result":
                    result, completed = value, True
                    last_activity = time.monotonic()
                    stage = "đóng tiến trình"
                elif kind == "error":
                    raise RuntimeError(value)
            if time.monotonic() - last_activity > timeout:
                raise TimeoutError(f"{task_name} quá {timeout:g}s không tiến triển tại bước: {stage}. {interrupted_warning}")
            if time.monotonic() >= next_wait_notice:
                log(f"Đang chờ {stage} ({time.monotonic() - last_activity:.0f}s). Giao diện vẫn hoạt động; có thể Hủy để ngắt ngay.")
                next_wait_notice = time.monotonic() + 10
    except OperationCancelledError as exc:
        raise OperationCancelledError(interrupted_warning) from exc
    finally:
        stopped.set()
        sender.close()
        if started:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=1)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=1)
            if worker.is_alive():
                # Keep the owning job occupied instead of allowing another writer.
                log("Không thể xác nhận tiến trình đã dừng; đang chờ hệ điều hành giải phóng. Không chạy tác vụ khác.")
                worker.join()
            worker.close()
        if reader.ident is not None:
            reader.join(timeout=1)
        else:
            receiver.close()


class ObservedConnection:
    """Report call boundaries without exposing SQL text, parameters or credentials."""
    def __init__(self, connection, activity, label, fast_batch=False):
        self._connection = connection
        self._activity = activity
        self._label = label
        self._fast_batch = fast_batch

    def __getattr__(self, name):
        value = getattr(self._connection, name)
        if name not in {"cursor", "commit", "rollback", "close"}:
            return value

        def call(*args, **kwargs):
            self._activity(f"{self._label}: {name}")
            result = value(*args, **kwargs)
            self._activity(f"{self._label}: đã {name}")
            if name == "cursor":
                if self._fast_batch and hasattr(result, "fast_executemany"):
                    result.fast_executemany = True
                return ObservedCursor(result, self._activity, self._label)
            return result
        return call


class ObservedCursor:
    def __init__(self, cursor, activity, label):
        object.__setattr__(self, "_cursor", cursor)
        object.__setattr__(self, "_activity", activity)
        object.__setattr__(self, "_label", label)

    def __setattr__(self, name, value):
        setattr(self._cursor, name, value)

    def __getattr__(self, name):
        value = getattr(self._cursor, name)
        if name not in {"execute", "executemany", "fetchone", "fetchmany", "fetchall", "close"}:
            return value

        def call(*args, **kwargs):
            self._activity(f"{self._label}: {name}")
            result = value(*args, **kwargs)
            self._activity(f"{self._label}: đã {name}")
            return self if result is self._cursor else result
        return call
