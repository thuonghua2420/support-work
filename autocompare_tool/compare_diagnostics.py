"""Readable, composable error context for CSV comparison stages."""

from __future__ import annotations

import errno
from contextlib import contextmanager
from typing import Iterator


class CompareDiagnosticError(ValueError):
    def __init__(self, message: str, *, hint: str = "", **context: object) -> None:
        self.message = message
        self.hint = hint
        self.context = context
        super().__init__(message)

    def __str__(self) -> str:
        lines = [self.message]
        lines.extend(f"{key}: {value}" for key, value in self.context.items() if value is not None and value != "")
        if self.hint:
            lines.append(f"Cách kiểm tra: {self.hint}")
        return "\n".join(lines)


def describe_failure(exc: Exception, **context: object) -> CompareDiagnosticError:
    if isinstance(exc, CompareDiagnosticError):
        exc.context = {**context, **exc.context}
        return exc
    hint = "Kiểm tra đường dẫn và dữ liệu tại vị trí được ghi trong thông báo."
    if isinstance(exc, MemoryError):
        hint = "Không đủ RAM để xử lý. Chia nhỏ cặp CSV hoặc giảm số file trong một workbook rồi chạy lại."
    elif isinstance(exc, PermissionError):
        hint = "Đóng file CSV/Excel đang mở và kiểm tra quyền đọc/ghi của file cùng thư mục đích."
    elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        hint = "Ổ đĩa không đủ dung lượng. Kiểm tra cả ổ chứa thư mục đích và thư mục tạm."
    elif isinstance(exc, UnicodeError):
        hint = "Kiểm tra encoding; CSV compare hỗ trợ UTF-8 (có/không BOM) và CP932."
    detail = str(exc)
    if len(detail) > 1500:
        detail = detail[:1500] + " ... [rút gọn nội dung lỗi kỹ thuật]"
    return CompareDiagnosticError(
        "Không thể hoàn tất compare.", hint=hint, **context,
        **{"Loại lỗi": type(exc).__name__, "Chi tiết kỹ thuật": detail or type(exc).__name__},
    )


@contextmanager
def compare_context(stage: str, **context: object) -> Iterator[None]:
    try:
        yield
    except Exception as exc:
        failure = describe_failure(exc, **{"Giai đoạn": stage, **context})
        if failure is exc:
            raise
        raise failure from exc


def csv_location(record: int, column: int | None = None, name: str | None = None,
                 lines: tuple[int, int] | None = None) -> dict[str, object]:
    return {
        "Record CSV": record if record else "Header",
        "Dòng vật lý CSV": (str(lines[0]) if lines[0] == lines[1] else f"{lines[0]}–{lines[1]}") if lines else None,
        "Cột CSV": column,
        "Tên column": (repr(name[:200]) + (f" ... ({len(name)} ký tự)" if len(name) > 200 else "")) if name is not None else None,
    }
