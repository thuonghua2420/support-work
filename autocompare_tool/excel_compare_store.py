from __future__ import annotations

import atexit
import shutil
import sqlite3
import tempfile
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING
from uuid import uuid4

from openpyxl.utils import column_index_from_string, get_column_letter

if TYPE_CHECKING:
    from .excel_compare import ExcelCompareResult, SheetCompareSummary


CHANGE_TYPES = ("changed", "added", "removed", "kind", "formula")
MAX_EXCEL_COLUMNS = 16_384
DiffRow = tuple[int, int, int, str, str, str, str, str]
_root_path: Path | None = None
_root_lock = Lock()


def _report_directory() -> Path:
    global _root_path
    with _root_lock:
        if _root_path is None:
            _root_path = Path(tempfile.mkdtemp(prefix="autocompare_excel_"))
            atexit.register(shutil.rmtree, _root_path, ignore_errors=True)
        return _root_path


class ExcelCompareStore:
    """Spool cell differences to disk and retain the last three completed reports."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: set[str] = set()
        self._reports: dict[str, ExcelCompareResult] = {}

    def create(self) -> str:
        report_id = uuid4().hex
        path = self._path(report_id)
        try:
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("""
                    PRAGMA journal_mode = DELETE;
                    PRAGMA synchronous = OFF;
                    CREATE TABLE diffs (
                        id INTEGER PRIMARY KEY,
                        sheet_idx INTEGER,
                        row INTEGER,
                        col INTEGER,
                        coord TEXT,
                        change_type TEXT,
                        header TEXT,
                        old_text TEXT,
                        new_text TEXT
                    );
                    CREATE INDEX diffs_sheet_id ON diffs(sheet_idx, id);
                    CREATE INDEX diffs_sheet_col ON diffs(sheet_idx, col);
                """)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        with self._lock:
            self._pending.add(report_id)
        return report_id

    def add_batch(self, report_id: str, rows: Iterable[DiffRow]) -> None:
        with self._lock:
            if report_id not in self._pending:
                raise FileNotFoundError("Báo cáo so sánh Excel không còn mở để ghi.")
            with closing(sqlite3.connect(self._path(report_id))) as connection, connection:
                connection.execute("PRAGMA synchronous = OFF")
                connection.executemany("""
                    INSERT INTO diffs (sheet_idx, row, col, coord, change_type, header, old_text, new_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, rows)

    def finish(self, summary: ExcelCompareResult) -> None:
        with self._lock:
            if summary.report_id not in self._pending:
                raise FileNotFoundError("Báo cáo so sánh Excel không còn mở để ghi.")
            if len(self._reports) >= 3:
                oldest = next(iter(self._reports))
                self._path(oldest).unlink(missing_ok=True)
                del self._reports[oldest]
            self._pending.remove(summary.report_id)
            self._reports[summary.report_id] = summary

    def _sheet(self, report_id: str, sheet_idx: int) -> SheetCompareSummary:
        summary = self._reports.get(report_id)
        if summary is None:
            raise FileNotFoundError("Báo cáo so sánh Excel không tồn tại hoặc đã hết hạn. Hãy so sánh lại.")
        if not 0 <= sheet_idx < len(summary.sheets):
            raise ValueError("Chỉ số sheet không hợp lệ.")
        return summary.sheets[sheet_idx]

    def sheet_truncated(self, report_id: str, sheet_idx: int) -> bool:
        with self._lock:
            return self._sheet(report_id, sheet_idx).details_truncated

    def query(
        self,
        report_id: str,
        sheet_idx: int,
        offset: int = 0,
        limit: int = 200,
        search: str = "",
        change_types: Iterable[str] = (),
        column: str = "",
    ) -> tuple[int, list[dict[str, int | str]]]:
        conditions = ["sheet_idx = ?"]
        params: list[int | str] = [sheet_idx]
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(r"(coord LIKE ? ESCAPE '\' OR old_text LIKE ? ESCAPE '\' "
                              r"OR new_text LIKE ? ESCAPE '\' OR header LIKE ? ESCAPE '\')")
            params.extend([f"%{escaped}%"] * 4)
        types = tuple(dict.fromkeys(change_types))
        if types:
            conditions.append(f"change_type IN ({', '.join('?' for _ in types)})")
            params.extend(types)
        if column:
            try:
                column_index = column_index_from_string(column)
            except ValueError:
                raise ValueError("Cột Excel phải nằm trong khoảng A đến XFD.") from None
            if column_index > MAX_EXCEL_COLUMNS:
                raise ValueError("Cột Excel phải nằm trong khoảng A đến XFD.")
            conditions.append("col = ?")
            params.append(column_index)
        where = " AND ".join(conditions)
        with self._lock:
            self._sheet(report_id, sheet_idx)
            with closing(sqlite3.connect(self._path(report_id))) as connection:
                total = connection.execute(f"SELECT COUNT(*) FROM diffs WHERE {where}", params).fetchone()[0]
                offset = max(0, offset)
                if offset >= total:
                    return total, []
                rows = connection.execute(
                    f"""
                    SELECT row, col, coord, change_type, header, old_text, new_text
                    FROM diffs WHERE {where} ORDER BY id LIMIT ? OFFSET ?
                    """,
                    (*params, min(500, max(1, limit)), offset),
                ).fetchall()
        return total, [
            {"row": row, "col": col, "coord": coord, "column": get_column_letter(col),
             "change_type": change_type, "header": header, "old": old, "new": new}
            for row, col, coord, change_type, header, old, new in rows
        ]

    def delete(self, report_id: str) -> None:
        with self._lock:
            if report_id in self._pending or report_id in self._reports:
                self._path(report_id).unlink(missing_ok=True)
                self._pending.discard(report_id)
                self._reports.pop(report_id, None)

    @staticmethod
    def _path(report_id: str) -> Path:
        return _report_directory() / f"{report_id}.sqlite3"


default_store = ExcelCompareStore()
