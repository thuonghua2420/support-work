"""Read-only folder comparison and explicit, conflict-checked text editing."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import threading
import uuid
from collections import Counter
from pathlib import Path

MAX_TEXT_BYTES = 1_000_000
MAX_TEXT_LINES = 10000
MAX_ENTRIES = 20000
DEFAULT_EXCLUDE = r"(^|/)(\.git|node_modules|__pycache__)(/|$)|\.(log|tmp)$"


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _decode(data):
    if data.startswith(b"\xff\xfe\x00\x00"):
        encoding = "utf-32"
    elif data.startswith(b"\x00\x00\xfe\xff"):
        encoding = "utf-32"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif data.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
        try:
            data.decode(encoding)
        except UnicodeDecodeError:
            encoding = "cp932"
    try:
        text = data.decode(encoding)
    except UnicodeError as exc:
        raise ValueError("Không đọc được encoding. Hỗ trợ UTF-8, UTF-16/32 có BOM và CP932.") from exc
    if any(ord(c) < 32 and c not in "\t\r\n\f" for c in text):
        raise ValueError("File nhị phân không mở bằng trình chỉnh sửa văn bản. Dùng Folder Compare để đối chiếu byte.")
    if len(text.splitlines()) > MAX_TEXT_LINES:
        raise ValueError(f"Trình chỉnh sửa hỗ trợ tối đa {MAX_TEXT_LINES:,} dòng mỗi file.")
    return text, encoding


def _read(path):
    if _linked(path):
        raise ValueError("Không chỉnh sửa symlink/junction. Hãy chọn trực tiếp file đích.")
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Chỉ mở file văn bản thông thường.")
        data = stream.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError("File quá lớn để chỉnh sửa: tối đa 1 MB mỗi file. Folder Compare vẫn so sánh được file lớn.")
    return data


class TextCompareFiles:
    def __init__(self):
        self._lock = threading.Lock()
        self._files = {}

    def open(self, raw_path):
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("Hãy chọn file cần mở.")
        path = Path(raw_path).absolute()
        data = _read(path)
        path = path.resolve()
        text, encoding = _decode(data)
        token = uuid.uuid4().hex
        with self._lock:
            while len(self._files) >= 64:
                del self._files[next(iter(self._files))]
            self._files[token] = (path, data, encoding)
        endings = Counter(re.findall(r"\r\n|\r|\n", text))
        eol = next(iter(endings), "\n") if len(endings) <= 1 else "mixed"
        return {"token": token, "path": str(path), "name": path.name, "text": text,
                "encoding": encoding, "eol": eol, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}

    def save(self, payload):
        if payload.get("confirmed") is not True:
            raise PermissionError("Cần xác nhận ghi đè file trên giao diện.")
        text = payload.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT_BYTES or len(text.splitlines()) > MAX_TEXT_LINES:
            raise ValueError("Nội dung không hợp lệ hoặc vượt giới hạn 1 MB / 10.000 dòng.")
        with self._lock:
            record = self._files.get(payload.get("token"))
            if record is None:
                raise ValueError("Phiên mở file đã hết hạn. Hãy mở lại file trước khi lưu.")
            path, original, encoding = record
            if payload.get("sha256") != hashlib.sha256(original).hexdigest():
                raise RuntimeError("Bản đang chỉnh sửa đã cũ. Hãy mở lại file trước khi lưu.")
            eol = payload.get("eol", "original")
            if eol == "original":
                endings = set(re.findall(r"\r\n|\r|\n", original.decode(encoding)))
                if len(endings) > 1:
                    raise ValueError("File có nhiều kiểu xuống dòng. Chọn LF hoặc CRLF trước khi lưu.")
                eol = next(iter(endings), "\n")
            if eol not in {"\r\n", "\n", "\r"}:
                raise ValueError("Kiểu xuống dòng không hợp lệ.")
            text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", eol)
            # Preserve original BOM endianness, not the platform's native order.
            codec, bom = encoding, b""
            for marker, specific in [(b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")]:
                if original.startswith(marker):
                    codec, bom = specific, marker
                    break
            try:
                data = bom + text.encode(codec)
            except UnicodeError as exc:
                raise ValueError("Nội dung mới không biểu diễn được trong encoding gốc. Tải bản UTF-8 để giữ nguyên file gốc.") from exc
            if len(data) > MAX_TEXT_BYTES:
                raise ValueError("Nội dung sau mã hóa vượt giới hạn 1 MB.")
            if _read(path) != original:
                raise RuntimeError("File đã thay đổi bên ngoài. Không ghi đè; tải bản chỉnh sửa rồi mở lại file để đối chiếu.")
            mode = path.stat().st_mode
            if not mode & stat.S_IWRITE:
                raise PermissionError("File chỉ đọc; hãy tải bản sao thay vì ghi đè.")
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".compare-", delete=False) as stream:
                    temp_path = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temp_path, stat.S_IMODE(mode))
                if _read(path) != original:
                    raise RuntimeError("File vừa thay đổi bên ngoài; đã chặn ghi đè.")
                os.replace(temp_path, path)
                self._files[payload["token"]] = (path, data, encoding)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
        return {"saved": True, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def compare_text_folders(left, right, include="", exclude=DEFAULT_EXCLUDE, activity=None, log=None):
    if not str(left).strip() or not str(right).strip():
        raise ValueError("Hãy chọn đủ hai thư mục.")
    roots = [Path(left).resolve(), Path(right).resolve()]
    if not all(root.is_dir() for root in roots):
        raise ValueError("Hãy chọn hai thư mục tồn tại.")
    if len(include) > 1000 or len(exclude) > 1000:
        raise ValueError("Regex tối đa 1.000 ký tự.")
    try:
        include_re = re.compile(include) if include else None
        exclude_re = re.compile(exclude) if exclude else None
    except re.error as exc:
        raise ValueError(f"Regex không hợp lệ: {exc}") from exc
    tick = activity or (lambda _: None)
    entries = []
    for root in roots:
        found, pending = {}, [(root, "")]
        visited = 0
        while pending:
            directory, prefix = pending.pop()
            tick(f"Quét {prefix or root.name}")
            try:
                with os.scandir(directory) as children:
                    for child in children:
                        visited += 1
                        if visited > MAX_ENTRIES:
                            raise ValueError("Thư mục vượt 20.000 mục; hãy chọn thư mục con hoặc thu hẹp phạm vi.")
                        relative = prefix + child.name
                        if exclude_re and exclude_re.search(relative):
                            continue
                        path = Path(child.path)
                        if _linked(path):
                            found[relative] = ("skipped", "Bỏ qua symlink/junction")
                        elif child.is_dir(follow_symlinks=False):
                            found[relative] = ("directory", "")
                            pending.append((path, relative + "/"))
                        elif child.is_file(follow_symlinks=False) and (not include_re or include_re.search(relative)):
                            found[relative] = ("file", "")
                        elif not child.is_file(follow_symlinks=False):
                            found[relative] = ("skipped", "Bỏ qua mục đặc biệt không phải file/thư mục thông thường")
            except OSError as exc:
                found[prefix.rstrip("/") or "."] = ("error", str(exc))
        entries.append(found)
    rows = []
    for relative in sorted(entries[0].keys() | entries[1].keys(), key=lambda x: (x.casefold(), x)):
        tick(f"So sánh {relative}")
        a, b = entries[0].get(relative), entries[1].get(relative)
        row = {"path": relative, "kind": (a or b)[0], "left": str(roots[0] / relative) if a else "", "right": str(roots[1] / relative) if b else "", "detail": ""}
        inaccessible_parent = None
        for side, item in enumerate((a, b)):
            if item is not None:
                continue
            parts = relative.split("/")
            for parent in ["."] + ["/".join(parts[:n]) for n in range(1, len(parts))]:
                ancestor = entries[side].get(parent)
                if ancestor and ancestor[0] in {"error", "skipped"}:
                    inaccessible_parent = (ancestor[0], f"Không xác định: thư mục {'trái' if side == 0 else 'phải'} {parent} không được đọc. {ancestor[1]}")
                    break
        if inaccessible_parent:
            row.update(status=inaccessible_parent[0], detail=inaccessible_parent[1])
        elif any(item and item[0] in {"error", "skipped"} for item in (a, b)):
            row.update(status="error" if any(item and item[0] == "error" for item in (a, b)) else "skipped", detail="; ".join(item[1] for item in (a, b) if item and item[1]))
        elif not a or not b:
            row["status"] = "left-only" if a else "right-only"
        elif a[0] != b[0]:
            row.update(status="type-conflict", detail="Một bên là file, bên còn lại là thư mục.")
        elif a[0] == "directory":
            row["status"] = "folder"
        else:
            try:
                paths = [roots[0] / relative, roots[1] / relative]
                if any(_linked(path) or not path.resolve().is_relative_to(root) for path, root in zip(paths, roots)):
                    raise OSError("Đường dẫn đổi thành liên kết hoặc nằm ngoài thư mục được chọn.")
                before = [p.stat() for p in paths]
                equal = before[0].st_size == before[1].st_size
                if equal:
                    with paths[0].open("rb") as first, paths[1].open("rb") as second:
                        while True:
                            tick(f"Đọc nội dung {relative}")
                            chunk = first.read(262144)
                            if chunk != second.read(262144):
                                equal = False
                                break
                            if not chunk:
                                break
                after = [p.stat() for p in paths]
                if any((x.st_size, x.st_mtime_ns, x.st_ino) != (y.st_size, y.st_mtime_ns, y.st_ino) for x, y in zip(before, after)):
                    raise OSError("File thay đổi trong lúc quét; cần quét lại.")
                row.update(status="same" if equal else "different", left_size=before[0].st_size, right_size=before[1].st_size)
            except OSError as exc:
                row.update(status="error", detail=str(exc))
        rows.append(row)
    counts = dict(Counter(row["status"] for row in rows if row["status"] != "folder"))
    if log:
        log(f"Đã đối chiếu {len(rows)} mục. Giống nhau là giống byte, không chỉ tên hoặc kích thước.")
    return {"rows": rows, "counts": counts, "left": str(roots[0]), "right": str(roots[1])}


def _folder_worker(sender, args, kwargs):
    try:
        result = compare_text_folders(*args, **kwargs, activity=lambda message: sender.send(("activity", message)), log=lambda message: sender.send(("log", message)))
        sender.send(("result", result))
    except Exception as exc:
        sender.send(("error", str(exc)))
    finally:
        sender.close()


def run_folder_compare(left, right, include="", exclude=DEFAULT_EXCLUDE, log=None, cancel=None):
    from .database_sync_worker import _run_worker
    return _run_worker(_folder_worker, (left, right, include, exclude), {}, log or (lambda _: None), cancel, 30,
                       task_name="So sánh thư mục", interrupted_warning="Đã ngắt quét thư mục. Không thay đổi file nguồn.")
