"""Read and persist the editable UT comparison tree without rewriting other settings."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile

from .app_config import default_config_path, load_app_config, validate_case_pattern

WORKBOOK_KEYS = ("htm_before_after_file", "htc_before_after_file", "after_htc_vs_htm_file")
_LABELS = {
    "case_pattern": "Mẫu tên case",
    "input_dir": "CSV nguồn", "output_dir": "Output", "compare_dir": "Compare",
    "before_htm_dir": "HTM / Before", "after_htm_dir": "HTM / After",
    "before_htc_dir": "HTC / Before", "after_htc_dir": "HTC / After",
    "htm_before_after_file": "File HTM trước / sau", "htc_before_after_file": "File HTC trước / sau",
    "after_htc_vs_htm_file": "File HTC sau / HTM sau",
}
_SAVE_LOCK = threading.Lock()


def read_compare_structure(config_path: Path | None = None) -> dict:
    path = config_path if config_path is not None else default_config_path()
    with _SAVE_LOCK:
        return _snapshot(path)


def _snapshot(path: Path) -> dict:
    raw = path.read_bytes() if path.exists() else b""
    config = load_app_config(path)
    return {
        "folders": asdict(config.folders),
        "workbooks": {key: getattr(config.workbooks, key) for key in WORKBOOK_KEYS},
        "revision": hashlib.sha256(raw).hexdigest(),
    }


def _validate_name(value: object, label: str, *, workbook: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: tên không được để trống.")
    name = value.strip()
    if len(name) > 255 or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', name) or name.endswith("."):
        raise ValueError(f"{label}: nhập một tên hợp lệ, không chứa đường dẫn hoặc ký tự < > : \" / \\ | ? *.")
    reserved = name.split(".", 1)[0].rstrip(" .").upper()
    if reserved in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", *[f"{prefix}{i}" for prefix in ("COM", "LPT") for i in "123456789¹²³"]}:
        raise ValueError(f"{label}: tên này được Windows dành riêng.")
    if workbook and not name.lower().endswith(".xlsx"):
        raise ValueError(f"{label}: tên file phải có đuôi .xlsx.")
    return name


def _unique(values: list[str], label: str) -> None:
    if len({value.casefold() for value in values}) != len(values):
        raise ValueError(f"{label}: các tên cùng cấp không được trùng nhau.")


def _update_sections(text: str, changes: dict[str, dict[str, str]]) -> str:
    # ConfigParser validates the document when loading; this narrow edit retains
    # comments, Japanese names, unknown options, BOM and original line endings.
    newline = "\r\n" if "\r\n" in text else "\n"
    pending = {section: dict(values) for section, values in changes.items()}
    output: list[str] = []
    section = ""
    skip_continuation = False
    for line in text.splitlines(keepends=True):
        heading = re.match(r"^\s*\[([^]]+)\]", line)
        if heading:
            if pending.get(section):
                output.extend(f"{key} = {value}{newline}" for key, value in pending[section].items())
                pending[section].clear()
            section = heading[1]
            skip_continuation = False
        option = re.match(r"^([^\s#;][^=:]*?)\s*[=:]", line)
        if option:
            key = option[1].strip().lower()
            skip_continuation = key in changes.get(section, {})
            if skip_continuation:
                output.append(f"{key} = {changes[section][key]}{newline}")
                pending[section].pop(key, None)
                continue
        elif skip_continuation and line[:1].isspace() and line.strip() and not line.lstrip().startswith(("#", ";")):
            continue
        output.append(line)
    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] += newline
    for name, values in pending.items():
        if not values:
            continue
        if name != section:
            output.append(f"{newline}[{name}]{newline}")
        output.extend(f"{key} = {value}{newline}" for key, value in values.items())
    return "".join(output)


def save_compare_structure(payload: dict, config_path: Path | None = None) -> dict:
    path = config_path if config_path is not None else default_config_path()
    with _SAVE_LOCK:
        current = _snapshot(path)
        if not payload.get("revision") or payload["revision"] != current["revision"]:
            raise RuntimeError("Cấu hình đã thay đổi ở nơi khác. Nhấn Tải lại để lấy bản mới nhất trước khi lưu.")
        values = {}
        for section in ("folders", "workbooks"):
            supplied = payload.get(section)
            if not isinstance(supplied, dict) or set(supplied) != set(current[section]):
                raise ValueError(f"Cấu hình {section} không đầy đủ hoặc chứa thuộc tính không hợp lệ.")
            values[section] = {key: validate_case_pattern(value) if key == "case_pattern" else _validate_name(value, _LABELS[key], workbook=section == "workbooks")
                               for key, value in supplied.items()}
        folders = values["folders"]
        _unique([folders["input_dir"], folders["output_dir"]], "Folder trong case")
        _unique([value for key, value in folders.items() if key not in {"case_pattern", "input_dir", "output_dir"}], "Folder trong Output")
        _unique(list(values["workbooks"].values()), "File compare")
        raw = path.read_bytes() if path.exists() else b""
        if hashlib.sha256(raw).hexdigest() != payload["revision"]:
            raise RuntimeError("Cấu hình đã thay đổi trong lúc lưu. Nhấn Tải lại rồi thử lại.")
        bom = raw.startswith(b"\xef\xbb\xbf")
        updated = _update_sections(raw.decode("utf-8-sig"), values)
        encoded = updated.encode("utf-8-sig" if bom else "utf-8")
        with NamedTemporaryFile(dir=path.parent, prefix=".compare-config-", suffix=".ini", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
        try:
            load_app_config(temporary_path)
            latest = path.read_bytes() if path.exists() else b""
            if latest != raw:
                raise RuntimeError("Cấu hình đã thay đổi trong lúc lưu. Nhấn Tải lại rồi thử lại.")
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return _snapshot(path)
