"""Folder search and byte-preserving replacement, independent of the web UI.

Search runs in a disposable process: even a pathological regex can be cancelled.
Only an explicitly previewed plan can write; offsets always refer to raw decoded
text (never browser-normalized text). Unchanged byte ranges are copied verbatim.
"""
from __future__ import annotations

import atexit
import bisect
import codecs
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MATCHES = 20000
MAX_FILES = 100000
MAX_PLAN_BYTES = 128 * 1024 * 1024
DEFAULT_EXCLUDE = "**/.git/**, **/node_modules/**, **/__pycache__/**, **/.venv/**"
BOMS = [(codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
        (codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")]


def linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def read_file(path, *, check_parents=True):
    if any(linked(p) for p in ((path, *path.parents) if check_parents else (path,))):
        raise ValueError("Không đọc/ghi qua symlink hoặc junction.")
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Không phải file thông thường.")
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File vượt giới hạn 8 MiB.")
    return data


def decode_file(data, requested="auto"):
    bom, codec = next(((b, c) for b, c in BOMS if data.startswith(b)), (b"", ""))
    body = data[len(bom):]
    if not codec:
        if requested not in {"auto", "utf-8", "cp932", "shift_jis"}:
            raise ValueError("Encoding không hợp lệ.")
        codec = requested
        if codec == "auto":
            try:
                body.decode("utf-8", errors="strict")
                codec = "utf-8"
            except UnicodeDecodeError:
                codec = "cp932"
    text = body.decode(codec, errors="strict")
    if re.search(r"[\x00-\x08\x0b\x0e-\x1f]", text):
        raise ValueError("Bỏ qua file nhị phân.")
    return text, codec, bom


def split_globs(value):
    parts, start, depth = [], 0, 0
    for i, char in enumerate(value):
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:i].strip())
            start = i + 1
    parts.append(value[start:].strip())
    return [p for p in parts if p]


def expand_braces(pattern):
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    result = []
    for item in match[1].split(","):
        result.extend(expand_braces(pattern[:match.start()] + item + pattern[match.end():]))
        if len(result) > 256:
            raise ValueError("Quá nhiều tổ hợp glob.")
    return result


def compile_globs(value):
    patterns = []
    for raw in split_globs(value):
        for glob in expand_braces(raw.replace("\\", "/").rstrip("/")):
            anchored = glob.startswith("./")
            glob = glob[2:] if anchored else glob
            out, i = ("" if anchored else "(?:.*/)?"), 0
            while i < len(glob):
                c = glob[i]
                if glob[i:i + 3] == "**/":
                    out += "(?:.*/)?"
                    i += 3
                elif glob[i:i + 2] == "**":
                    out += ".*"
                    i += 2
                elif c == "*":
                    out += "[^/]*"
                    i += 1
                elif c == "?":
                    out += "[^/]"
                    i += 1
                elif c == "[" and "]" in glob[i + 1:]:
                    end = glob.index("]", i + 1)
                    chars = glob[i + 1:end]
                    if chars.startswith("!"):
                        chars = "^" + chars[1:]
                    out += "[" + chars + "]"
                    i = end + 1
                else:
                    out += re.escape(c)
                    i += 1
            patterns.append(re.compile("^" + out + "(?:/.*)?$", re.IGNORECASE if os.name == "nt" else 0))
    return patterns


def compile_query(options):
    query = options.get("query", "")
    if not isinstance(query, str) or not query or len(query) > 4096:
        raise ValueError("Nhập nội dung tìm kiếm (tối đa 4096 ký tự).")
    source = query if options.get("regex") else re.escape(query)
    # JS-style named captures/backreferences supported in addition to Python syntax.
    if options.get("regex"):
        source = re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", source)
        source = re.sub(r"\\k<([A-Za-z_]\w*)>", r"(?P=\1)", source)
    if options.get("whole_word"):
        source = r"(?<!\w)(?:" + source + r")(?!\w)"
    try:
        pattern = re.compile(source, re.MULTILINE | (0 if options.get("match_case") else re.IGNORECASE))
    except re.error as exc:
        raise ValueError(f"Regex không hợp lệ: {exc}") from exc
    if pattern.groups > 100:
        raise ValueError("Regex hỗ trợ tối đa 100 nhóm.")
    return pattern


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prefetched_files(paths):
    """Overlap disk reads, with at most eight files in memory, in stable order."""
    source = iter(paths)
    pending = deque()
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="search-read") as pool:
        def queue_one():
            path = next(source, None)
            if path is not None:
                pending.append((path, pool.submit(read_file, path, check_parents=False)))
        for _ in range(8):
            queue_one()
        try:
            while pending:
                yield pending.popleft()
                queue_one()
        finally:
            for _, future in pending:
                future.cancel()


def scan(options, emit):
    root = Path(options["root"]).resolve(strict=True)
    pattern = compile_query(options)
    include = compile_globs(options.get("include", ""))
    exclude = compile_globs(options.get("exclude", ""))
    scanned = count = skipped = 0
    limited = False
    started = time.monotonic()
    def walk_error(error):
        emit({"warning": str(error)})
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        base = Path(directory)
        if any(linked(p) for p in (base, *base.parents)):
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not linked(base / d) and not any(
            p.fullmatch((base / d).relative_to(root).as_posix() + "/") for p in exclude))
        def included_paths():
            for name in sorted(files):
                path = base / name
                relative = path.relative_to(root).as_posix()
                if any(p.fullmatch(relative) for p in exclude) or (include and not any(p.fullmatch(relative) for p in include)):
                    continue
                yield path
        for path, pending_read in prefetched_files(included_paths()):
            relative = path.relative_to(root).as_posix()
            scanned += 1
            if scanned > MAX_FILES:
                limited = True
                break
            try:
                # Ancestors are checked once per directory; file links are still
                # checked on every read. Preview/apply always recheck ancestors.
                data = pending_read.result()
                text, codec, bom = decode_file(data, options.get("encoding", "auto"))
                matches = []
                starts = None
                for match in pattern.finditer(text):
                    if count >= MAX_MATCHES:
                        limited = True
                        break
                    if starts is None:
                        starts = [0] + [m.end() for m in re.finditer(r"\r\n|\r|\n", text)]
                    line = bisect.bisect_right(starts, match.start()) - 1
                    endline = bisect.bisect_right(starts, match.end()) - 1
                    snippet_start = max(starts[line], match.start() - 80)
                    snippet_end = min(starts[line + 1] if line + 1 < len(starts) else len(text), match.start() + 240)
                    matches.append({"id": len(matches), "start": match.start(), "end": match.end(),
                                    "line": line + 1, "column": match.start() - starts[line] + 1,
                                    "end_line": endline + 1, "end_column": match.end() - starts[endline] + 1,
                                    "snippet": text[snippet_start:snippet_end].rstrip("\r\n"),
                                    "highlight_start": match.start() - snippet_start,
                                    "highlight_end": min(match.end(), snippet_end) - snippet_start,
                                    "groups": [match.span(i) for i in range(pattern.groups + 1)]})
                    count += 1
                if matches:
                    emit({"file": {"path": relative, "encoding": codec, "bom": bool(bom), "sha256": digest(data),
                                   "size": len(data), "matches": matches, "names": dict(pattern.groupindex)}})
            except (OSError, ValueError, UnicodeError) as exc:
                skipped += 1
                emit({"warning": f"{relative}: {exc}"})
            if scanned % 50 == 0:
                emit({"scanned": scanned, "count": count, "skipped": skipped})
            if limited:
                break
        if limited:
            break
    emit({"done": True, "scanned": scanned, "count": count, "skipped": skipped,
          "limited": limited, "elapsed": round(time.monotonic() - started, 3)})


def preserve_case(original, replacement):
    for separator in ("-", "_"):
        if separator in original and len(original.split(separator)) == len(replacement.split(separator)):
            return separator.join(preserve_case(a, b) for a, b in zip(original.split(separator), replacement.split(separator)))
    if original.isupper():
        return replacement.upper()
    if original.islower():
        return replacement.lower()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def replacement_text(template, match, text, names, regex=False, preserve=False):
    if not regex:
        result = template
    else:
        def group(number):
            if number >= len(match["groups"]):
                raise ValueError(f"Không có nhóm ${number} trong regex.")
            start, end = match["groups"][number]
            return "" if start < 0 else text[start:end]
        result, i, mode, once = "", 0, "", ""
        while i < len(template):
            char = template[i]
            value = char
            if char == "\\" and i + 1 < len(template):
                nxt = template[i + 1]
                if nxt in "uUlL":
                    if nxt.isupper():
                        mode = nxt
                    else:
                        once = nxt
                    i += 2
                    continue
                if nxt == "E":
                    mode = once = ""
                    i += 2
                    continue
                value = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\"}.get(nxt, "\\" + nxt)
                i += 2
            elif char == "$" and i + 1 < len(template):
                token = re.match(r"\$(\d{1,2}|&|\$|<[^>]+>)", template[i:])
                if token:
                    key = token[1]
                    if key == "$":
                        value = "$"
                    elif key == "&":
                        value = group(0)
                    elif key.startswith("<"):
                        if key[1:-1] not in names:
                            raise ValueError(f"Không có nhóm {key}.")
                        value = group(names[key[1:-1]])
                    else:
                        value = group(int(key))
                    i += len(token[0])
                else:
                    i += 1
            else:
                i += 1
            if mode:
                value = value.upper() if mode == "U" else value.lower()
            if once and value:
                value = (value[:1].upper() if once == "u" else value[:1].lower()) + value[1:]
                once = ""
            result += value
    return preserve_case(text[match["start"]:match["end"]], result) if preserve else result


def patch_bytes(data, text, codec, bom, edits):
    boundaries = sorted({0, len(text), *(p for start, end, _ in edits for p in (start, end))})
    offsets = {0: len(bom)}
    # CP932 has duplicate byte mappings. Fall back to decoding byte by byte when
    # re-encoding would change them; never normalize those untouched bytes.
    if bom + text.encode(codec, errors="strict") == data:
        previous, position = 0, len(bom)
        for boundary in boundaries[1:]:
            position += len(text[previous:boundary].encode(codec, errors="strict"))
            offsets[boundary] = position
            previous = boundary
    else:
        decoder = codecs.getincrementaldecoder(codec)(errors="strict")
        char_position = 0
        wanted = set(boundaries)
        for position in range(len(bom), len(data)):
            decoded = decoder.decode(data[position:position + 1])
            char_position += len(decoded)
            if decoded and char_position in wanted:
                offsets[char_position] = position + 1
        offsets[0] = len(bom)
    pieces, last, size = [bom], len(bom), len(bom)
    for start, end, replacement in edits:
        encoded = data[offsets[start]:offsets[end]] if replacement == text[start:end] else replacement.encode(codec, errors="strict")
        if encoded.decode(codec, errors="strict") != replacement:
            raise UnicodeError(f"Replacement không round-trip nguyên ký tự qua {codec}.")
        size += offsets[start] - last + len(encoded)
        if size > MAX_FILE_BYTES:
            raise ValueError("Nội dung sau replace vượt giới hạn 8 MiB.")
        pieces.extend((data[last:offsets[start]], encoded))
        last = offsets[end]
    if size + len(data) - last > MAX_FILE_BYTES:
        raise ValueError("Nội dung sau replace vượt giới hạn 8 MiB.")
    pieces.append(data[last:])
    return b"".join(pieces)


def atomic_write(path, data):
    temporary = None
    try:
        mode = path.stat().st_mode
        if not mode & stat.S_IWRITE:
            raise PermissionError(f"File chỉ đọc: {path.name}")
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".autocompare-replace-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(mode))
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class SearchReplace:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None
        self.plan = None
        self.undo_plan = None
        atexit.register(self.close)

    def close(self):
        with self.lock:
            if self.session and self.session["process"].poll() is None:
                self.session["process"].kill()
                self.session["process"].wait(timeout=5)

    def load(self, payload):
        root = Path(str(payload.get("root", ""))).absolute()
        if not payload.get("root") or not root.is_dir() or any(linked(p) for p in (root, *root.parents)):
            raise ValueError("Chọn folder tồn tại, không qua symlink/junction.")
        return {"root": str(root.resolve())}

    def start(self, payload):
        options = {k: payload.get(k, default) for k, default in {
            "query": "", "include": "", "exclude": DEFAULT_EXCLUDE, "encoding": "auto",
            "regex": False, "whole_word": False, "match_case": False}.items()}
        options.update(self.load(payload))
        compile_query(options)
        compile_globs(options["include"])
        compile_globs(options["exclude"])
        with self.lock:
            self.close()
            self.plan = None
            token = uuid.uuid4().hex
            process = subprocess.Popen([sys.executable, "-m", "autocompare_tool.search_replace", "--worker"],
                                       cwd=Path(__file__).resolve().parent.parent, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            session = {"id": token, "options": options, "process": process, "files": [], "warnings": [],
                       "done": False, "count": 0, "scanned": 0, "skipped": 0, "limited": False}
            self.session = session
            process.stdin.write(json.dumps(options) + "\n")
            process.stdin.close()
            threading.Thread(target=self._collect, args=(session,), daemon=True).start()
            timer = threading.Timer(120, self._timeout, args=(session,))
            timer.daemon = True
            timer.start()
            return {"id": token}

    def _timeout(self, session):
        with self.lock:
            if not session["done"]:
                session["error"] = "Search quá 120 giây. Thu hẹp folder/glob hoặc sửa regex rồi tìm lại."
                session["done"] = True
                session["process"].kill()

    def _collect(self, session):
        process = session["process"]
        try:
            for line in process.stdout:
                item = json.loads(line)
                with self.lock:
                    if "file" in item:
                        file = item["file"]
                        file["id"] = len(session["files"])
                        session["files"].append(file)
                        session["count"] += len(file["matches"])
                    elif "warning" in item:
                        if len(session["warnings"]) < 200:
                            session["warnings"].append(item["warning"])
                    else:
                        session.update(item)
            code = process.wait()
            with self.lock:
                if code and not session["done"]:
                    session["error"] = process.stderr.read()[-2000:] or "Search đã dừng."
                session["done"] = True
        finally:
            process.stdout.close()
            process.stderr.close()

    def _session(self, payload):
        if not self.session or payload.get("id") != self.session["id"]:
            raise ValueError("Kết quả đã cũ. Hãy tìm kiếm lại.")
        return self.session

    def poll(self, payload):
        with self.lock:
            session = self._session(payload)
            cursor = max(0, int(payload.get("cursor", 0)))
            files = session["files"][cursor:cursor + 30]
            return {**{k: session.get(k) for k in ("done", "count", "scanned", "skipped", "limited", "elapsed", "error", "warnings")},
                    "files": [{k: ([{mk: mv for mk, mv in m.items() if mk != "groups"} for m in v] if k == "matches" else v)
                               for k, v in f.items() if k != "names"} for f in files],
                    "cursor": cursor + len(files), "has_more": cursor + len(files) < len(session["files"])}

    def cancel(self, payload):
        with self.lock:
            session = self._session(payload)
            session.update(done=True, cancelled=True)
            self.close()
            return {"cancelled": True}

    def dismiss(self, payload):
        with self.lock:
            session = self._session(payload)
            if not session["done"]:
                raise ValueError("Đợi search hoàn tất trước khi bỏ kết quả.")
            for file in session["files"]:
                if file["id"] == payload.get("file_id"):
                    match_id = payload.get("match_id")
                    file["matches"] = [m for m in file["matches"] if match_id is not None and m["id"] != match_id]
            session["files"] = [f for f in session["files"] if f["matches"]]
            session["count"] = sum(len(f["matches"]) for f in session["files"])
            self.plan = None
            return {"count": session["count"]}

    def _current(self, session, file):
        path = Path(session["options"]["root"]) / file["path"]
        data = read_file(path)
        if digest(data) != file["sha256"]:
            raise ValueError(f"File đã thay đổi bên ngoài: {file['path']}. Tìm kiếm lại trước khi replace.")
        text, codec, bom = decode_file(data, file["encoding"])
        return path, data, text, codec, bom

    def preview(self, payload):
        with self.lock:
            session = self._session(payload)
            file = next((f for f in session["files"] if f["id"] == payload.get("file_id")), None)
            if file is None:
                raise ValueError("Không tìm thấy file trong kết quả.")
            _, data, text, codec, bom = self._current(session, file)
            edits = self._edits(session, file, text, payload)
            error, after = "", text
            try:
                after = patch_bytes(data, text, codec, bom, edits).decode("utf-8-sig" if bom == codecs.BOM_UTF8 else codec)
                if bom and bom != codecs.BOM_UTF8:
                    after = after[1:]
            except UnicodeError:
                error = f"Ký tự thay thế không biểu diễn được bằng {codec}; file sẽ không được ghi."
            return {"path": file["path"], "text": text, "after": after, "encoding": codec,
                    "bom": bool(bom), "error": error, "count": len(edits),
                    "eol": "/".join({"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[e] for e in dict.fromkeys(re.findall(r"\r\n|\r|\n", text))) or "—"}

    def _edits(self, session, file, text, payload):
        template = payload.get("replacement", "")
        if not isinstance(template, str) or len(template) > 100000:
            raise ValueError("Replacement tối đa 100.000 ký tự.")
        match_id = payload.get("match_id")
        matches = [m for m in file["matches"] if match_id is None or m["id"] == match_id]
        if not matches:
            raise ValueError("Không tìm thấy match.")
        edits, length = [], len(text)
        for match in matches:
            replacement = replacement_text(template, match, text, file["names"],
                                           bool(session["options"]["regex"]), bool(payload.get("preserve_case")))
            length += len(replacement) - (match["end"] - match["start"])
            if length > MAX_FILE_BYTES:
                raise ValueError("Nội dung sau replace vượt giới hạn 8 MiB.")
            edits.append((match["start"], match["end"], replacement))
        return edits

    def prepare(self, payload):
        with self.lock:
            self.plan = None
            session = self._session(payload)
            if not session["done"] or session.get("cancelled") or session.get("error") or session["limited"]:
                raise ValueError("Cần search hoàn tất, không bị cắt giới hạn, trước khi replace.")
            file_id = payload.get("file_id")
            if payload.get("match_id") is not None and file_id is None:
                raise ValueError("Replace một match cần chọn file.")
            files = [f for f in session["files"] if file_id is None or f["id"] == file_id]
            records, count, size = [], 0, 0
            for file in files:
                path, original, text, codec, bom = self._current(session, file)
                edits = self._edits(session, file, text, payload)
                try:
                    updated = patch_bytes(original, text, codec, bom, edits)
                except UnicodeError as exc:
                    raise ValueError(f"{file['path']}: replacement không biểu diễn được bằng {codec}.") from exc
                if len(updated) > MAX_FILE_BYTES:
                    raise ValueError(f"{file['path']}: kết quả vượt 8 MiB.")
                if not path.stat().st_mode & stat.S_IWRITE:
                    raise PermissionError(f"File chỉ đọc: {file['path']}")
                count += len(edits)
                if updated != original:
                    size += len(original) + len(updated)
                    if size > MAX_PLAN_BYTES:
                        raise ValueError("Replace vượt 128 MiB bộ nhớ. Thu hẹp files to include để chia đợt.")
                    records.append((path, original, updated))
            token = uuid.uuid4().hex
            self.plan = {"token": token, "records": records, "count": count}
            return {"token": token, "file_count": len(records), "count": count,
                    "files": [str(path.relative_to(Path(session['options']['root']))) for path, _, _ in records]}

    def apply(self, payload):
        if payload.get("confirmed") is not True:
            raise PermissionError("Cần xác nhận replace trên giao diện.")
        with self.lock:
            plan = self.plan
            if not plan or plan["token"] != payload.get("token"):
                raise ValueError("Bản preview hết hạn. Hãy xem trước lại.")
            result = self._write_records(plan["records"])
            self.undo_plan = [(p, after, before) for p, before, after in plan["records"] if str(p) in result["written"]]
            self.plan = None
            return {**result, "can_undo": bool(self.undo_plan)}

    def _write_records(self, records):
        # Preflight every file before writing any file. Also recheck immediately
        # before each atomic rename; report partial writes explicitly on I/O error.
        for path, before, _ in records:
            if read_file(path) != before:
                raise ValueError(f"File đã thay đổi: {path}. Không ghi file nào.")
            if not path.stat().st_mode & stat.S_IWRITE:
                raise PermissionError(f"File chỉ đọc: {path}")
        written, error = [], ""
        for path, before, after in records:
            try:
                if read_file(path) != before:
                    raise ValueError(f"File vừa thay đổi: {path}")
                atomic_write(path, after)
                written.append(str(path))
            except (OSError, ValueError) as exc:
                error = str(exc)
                break
        return {"written": written, "error": error}

    def undo(self, payload):
        if payload.get("confirmed") is not True:
            raise PermissionError("Cần xác nhận Undo.")
        with self.lock:
            if not self.undo_plan:
                raise ValueError("Không có replace để hoàn tác trong phiên này.")
            result = self._write_records(self.undo_plan)
            self.undo_plan = [r for r in self.undo_plan if str(r[0]) not in result["written"]]
            self.plan = None
            return {**result, "can_undo": bool(self.undo_plan)}


if __name__ == "__main__":
    try:
        scan(json.loads(sys.stdin.readline()), lambda event: print(json.dumps(event, ensure_ascii=True), flush=True))
    except Exception as error:
        print(json.dumps({"done": True, "error": str(error)}), flush=True)
