from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from openpyxl import load_workbook

Logger = Callable[[str], None]

INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


@dataclass
class FileUtilitySummary:
    action_name: str
    found_count: int = 0
    changed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)


def rename_exact_name(
    root_path: str | Path,
    old_name: str,
    new_name: str,
    include_files: bool = True,
    include_folders: bool = True,
    log: Logger | None = None,
) -> FileUtilitySummary:
    root = _validate_root_folder(root_path)
    old_name = _require_text(old_name, "Vui lòng nhập tên cũ.")
    new_name = _require_text(new_name, "Vui lòng nhập tên mới.")
    _validate_target_types(include_files, include_folders)
    logger = log or (lambda message: None)
    summary = FileUtilitySummary(action_name="Đổi tên chính xác")

    for path in _iter_paths_for_rename(root, include_files, include_folders):
        if path.name.casefold() != old_name.casefold():
            continue
        _rename_path(path, new_name, summary, logger)

    _log_summary(summary, logger)
    return summary


def rename_contains_text(
    root_path: str | Path,
    contains_text: str,
    replacement_text: str,
    include_files: bool = True,
    include_folders: bool = True,
    log: Logger | None = None,
) -> FileUtilitySummary:
    root = _validate_root_folder(root_path)
    contains_text = _require_text(contains_text, "Vui lòng nhập text cần tìm.")
    _validate_target_types(include_files, include_folders)
    logger = log or (lambda message: None)
    summary = FileUtilitySummary(action_name="Đổi tên chứa text")

    pattern = re.compile(re.escape(contains_text), flags=re.IGNORECASE)
    for path in _iter_paths_for_rename(root, include_files, include_folders):
        if not _contains(path.name, contains_text):
            continue
        new_name = pattern.sub(replacement_text, path.name)
        if not new_name.strip():
            summary.skipped_count += 1
            logger(f"[BỎ QUA] Tên mới bị rỗng: {path}")
            continue
        _rename_path(path, new_name, summary, logger)

    _log_summary(summary, logger)
    return summary


def delete_contains_text(
    root_path: str | Path,
    contains_text: str,
    include_files: bool = True,
    include_folders: bool = True,
    log: Logger | None = None,
) -> FileUtilitySummary:
    root = _validate_root_folder(root_path)
    contains_text = _require_text(contains_text, "Vui lòng nhập text cần tìm.")
    _validate_target_types(include_files, include_folders)
    logger = log or (lambda message: None)
    summary = FileUtilitySummary(action_name="Xóa chứa text")

    paths = [
        path
        for path in _iter_paths(root)
        if _matches_target_type(path, include_files, include_folders) and _contains(path.name, contains_text)
    ]
    for path in _sort_deepest_first(paths):
        if not path.exists():
            summary.skipped_count += 1
            continue
        summary.found_count += 1
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            summary.changed_count += 1
            logger(f"[ĐÃ XÓA] {path}")
        except Exception as exc:
            _record_error(summary, logger, path, exc)

    _log_summary(summary, logger)
    return summary


def rename_excel_sheets_contains(
    excel_path: str | Path,
    contains_text: str,
    replacement_text: str,
    log: Logger | None = None,
) -> FileUtilitySummary:
    path = _validate_excel_file(excel_path)
    contains_text = _require_text(contains_text, "Vui lòng nhập text cần tìm trong tên sheet.")
    logger = log or (lambda message: None)
    summary = FileUtilitySummary(action_name="Đổi tên sheet Excel")

    workbook = load_workbook(path)
    existing_names = set(workbook.sheetnames)
    pattern = re.compile(re.escape(contains_text), flags=re.IGNORECASE)

    for worksheet in workbook.worksheets:
        old_name = worksheet.title
        if not _contains(old_name, contains_text):
            continue
        summary.found_count += 1
        candidate = pattern.sub(replacement_text, old_name)
        new_name = _unique_sheet_name(candidate, existing_names, old_name)
        if old_name == new_name:
            summary.skipped_count += 1
            continue
        try:
            existing_names.remove(old_name)
            worksheet.title = new_name
            existing_names.add(new_name)
            summary.changed_count += 1
            logger(f"[ĐÃ ĐỔI TÊN SHEET] {old_name} -> {new_name}")
        except Exception as exc:
            existing_names.add(old_name)
            _record_error(summary, logger, path, exc)

    if summary.changed_count:
        workbook.save(path)
        logger(f"[ĐÃ LƯU] {path}")

    _log_summary(summary, logger)
    return summary


def move_files_contains_text(
    root_path: str | Path,
    contains_text: str,
    target_folder_name: str,
    log: Logger | None = None,
) -> FileUtilitySummary:
    root = _validate_root_folder(root_path)
    contains_text = _require_text(contains_text, "Vui lòng nhập text cần tìm trong tên file.")
    target_folder_name = _validate_single_folder_name(target_folder_name)
    logger = log or (lambda message: None)
    summary = FileUtilitySummary(action_name="Di chuyển file chứa text")

    for source_file in sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: str(path).lower()):
        if not _contains(source_file.name, contains_text):
            continue
        summary.found_count += 1
        target_folder = source_file.parent / target_folder_name
        if source_file.parent.name.casefold() == target_folder_name.casefold():
            summary.skipped_count += 1
            logger(f"[BỎ QUA] File đã nằm trong folder đích: {source_file}")
            continue
        try:
            target_folder.mkdir(parents=True, exist_ok=True)
            target_file = _unique_path(target_folder / source_file.name)
            shutil.move(str(source_file), str(target_file))
            summary.changed_count += 1
            logger(f"[ĐÃ DI CHUYỂN] {source_file} -> {target_file}")
        except Exception as exc:
            _record_error(summary, logger, source_file, exc)

    _log_summary(summary, logger)
    return summary


def find_empty_folders(root_path: str | Path, log: Logger | None = None) -> FileUtilitySummary:
    root = _validate_root_folder(root_path)
    logger = log or (lambda message: None)
    summary = FileUtilitySummary(action_name="Kiểm tra folder trống")

    for folder in _empty_folders(root):
        summary.found_count += 1
        logger(f"[FOLDER TRỐNG] {folder}")

    _log_summary(summary, logger)
    return summary


def delete_empty_folders(root_path: str | Path, log: Logger | None = None) -> FileUtilitySummary:
    root = _validate_root_folder(root_path)
    logger = log or (lambda message: None)
    summary = FileUtilitySummary(action_name="Xóa folder trống")

    folders = [path for path in root.rglob("*") if path.is_dir()]
    for folder in _sort_deepest_first(folders):
        try:
            if any(folder.iterdir()):
                continue
            summary.found_count += 1
            folder.rmdir()
            summary.changed_count += 1
            logger(f"[ĐÃ XÓA FOLDER TRỐNG] {folder}")
        except Exception as exc:
            _record_error(summary, logger, folder, exc)

    _log_summary(summary, logger)
    return summary


def _validate_root_folder(root_path: str | Path) -> Path:
    root = Path(root_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Folder thao tác không tồn tại: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Đường dẫn thao tác không phải là folder: {root}")
    return root


def _validate_excel_file(excel_path: str | Path) -> Path:
    path = Path(excel_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"File Excel không tồn tại: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Đường dẫn Excel không phải là file: {path}")
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("Vui lòng chọn file Excel .xlsx hoặc .xlsm.")
    return path


def _validate_single_folder_name(folder_name: str) -> str:
    folder_name = _require_text(folder_name, "Vui lòng nhập tên folder đích.")
    path = Path(folder_name)
    if path.is_absolute() or len(path.parts) != 1:
        raise ValueError("Tên folder đích chỉ được là tên folder, không nhập path.")
    return folder_name


def _require_text(value: str, message: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(message)
    return value


def _validate_target_types(include_files: bool, include_folders: bool) -> None:
    if not include_files and not include_folders:
        raise ValueError("Vui lòng chọn ít nhất file hoặc folder.")


def _iter_paths(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.exists()]


def _iter_paths_for_rename(root: Path, include_files: bool, include_folders: bool) -> list[Path]:
    paths = [path for path in _iter_paths(root) if _matches_target_type(path, include_files, include_folders)]
    return _sort_deepest_first(paths)


def _matches_target_type(path: Path, include_files: bool, include_folders: bool) -> bool:
    return (include_files and path.is_file()) or (include_folders and path.is_dir())


def _sort_deepest_first(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=lambda path: (len(path.parts), str(path).lower()), reverse=True)


def _contains(value: str, contains_text: str) -> bool:
    return contains_text.casefold() in value.casefold()


def _rename_path(path: Path, new_name: str, summary: FileUtilitySummary, logger: Logger) -> None:
    summary.found_count += 1
    if path.name == new_name:
        summary.skipped_count += 1
        logger(f"[BỎ QUA] Tên không đổi: {path}")
        return

    try:
        target_path = _unique_path(path.with_name(new_name))
        path.rename(target_path)
        summary.changed_count += 1
        logger(f"[ĐÃ ĐỔI TÊN] {path} -> {target_path}")
    except Exception as exc:
        _record_error(summary, logger, path, exc)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    if path.suffix:
        stem = path.stem
        suffix = path.suffix
        for index in range(1, 10000):
            candidate = path.with_name(f"{stem}_{index}{suffix}")
            if not candidate.exists():
                return candidate
    else:
        for index in range(1, 10000):
            candidate = path.with_name(f"{path.name}_{index}")
            if not candidate.exists():
                return candidate

    raise FileExistsError(f"Không tìm được tên chưa tồn tại cho: {path}")


def _unique_sheet_name(candidate: str, existing_names: set[str], old_name: str) -> str:
    base_name = INVALID_SHEET_CHARS.sub("_", candidate).strip().strip("'") or "Sheet"
    base_name = base_name[:31]
    if base_name == old_name:
        return old_name

    existing_casefold_names = {name.casefold() for name in existing_names if name != old_name}
    name = base_name
    index = 1
    while name.casefold() in existing_casefold_names:
        suffix = f"_{index}"
        name = f"{base_name[:31 - len(suffix)]}{suffix}"
        index += 1
    return name


def _empty_folders(root: Path) -> list[Path]:
    folders = [path for path in root.rglob("*") if path.is_dir()]
    empty: list[Path] = []
    for folder in _sort_deepest_first(folders):
        try:
            if not any(folder.iterdir()):
                empty.append(folder)
        except OSError:
            continue
    return empty


def _record_error(summary: FileUtilitySummary, logger: Logger, path: Path, exc: Exception) -> None:
    summary.error_count += 1
    message = f"[LỖI] {path}: {exc}"
    summary.errors.append(message)
    logger(message)


def _log_summary(summary: FileUtilitySummary, logger: Logger) -> None:
    logger(
        f"{summary.action_name} hoàn tất. "
        f"Tìm thấy {summary.found_count} mục, "
        f"xử lý {summary.changed_count} mục, "
        f"bỏ qua {summary.skipped_count} mục, "
        f"lỗi {summary.error_count} mục."
    )
