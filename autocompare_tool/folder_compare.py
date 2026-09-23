from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .app_config import (
    AppConfig,
    WORKFLOW_AFTER_HTC_VS_HTM,
    excel_headers_for_workflow,
    load_app_config,
)
from .excel_writer import WorkbookFixmeEntry, write_compare_workbook_for_pairs, write_compare_workbook_with_fixmes

Logger = Callable[[str], None]


@dataclass
class FolderCompareSummary:
    left_dir: Path
    right_dir: Path
    output_path: Path
    sheet_count: int = 0
    workbook_count: int = 1
    output_paths: list[Path] = field(default_factory=list)
    fixme_entries: list[WorkbookFixmeEntry] = field(default_factory=list)


@dataclass(frozen=True)
class FolderComparePair:
    left_name: str
    right_name: str
    output_name: str


def compare_csv_folders(
    left_dir: str | Path,
    right_dir: str | Path,
    output_path: str | Path,
    log: Logger | None = None,
    config: AppConfig | None = None,
) -> FolderCompareSummary:
    left = Path(left_dir).expanduser().resolve()
    right = Path(right_dir).expanduser().resolve()
    output = _normalize_output_path(Path(output_path).expanduser().resolve())
    logger = log or (lambda message: None)
    app_config = config or load_app_config()

    _validate_folder(left, "Folder bên trái")
    _validate_folder(right, "Folder bên phải")
    if output.exists() and output.is_dir():
        raise IsADirectoryError(f"File Excel xuất ra đang là folder: {output}")

    logger(f"Folder bên trái: {left}")
    logger(f"Folder bên phải: {right}")
    logger(f"File Excel xuất ra: {output}")

    result = write_compare_workbook_with_fixmes(
        left,
        right,
        output,
        excel_headers=excel_headers_for_workflow(app_config, WORKFLOW_AFTER_HTC_VS_HTM),
        case_folder_name=f"{left.name} - {right.name}",
        include_left_only_files=True,
        recursive=True,
    )
    logger(
        f"Đã tạo {result.output_path.name} "
        f"({result.sheet_count} sheet, {len(result.fixme_entries)} mục FIXME)."
    )

    return FolderCompareSummary(
        left_dir=left,
        right_dir=right,
        output_path=result.output_path,
        sheet_count=result.sheet_count,
        workbook_count=1,
        output_paths=[result.output_path],
        fixme_entries=result.fixme_entries,
    )


def preview_folder_compare_pairs(left_dir: str | Path, right_dir: str | Path) -> list[FolderComparePair]:
    left = Path(left_dir).expanduser().resolve()
    right = Path(right_dir).expanduser().resolve()
    _validate_folder(left, "Folder bên trái")
    _validate_folder(right, "Folder bên phải")
    return _default_pairs(left, right)


def compare_csv_folder_pairs(
    left_dir: str | Path,
    right_dir: str | Path,
    output_dir: str | Path,
    pairs: list[dict[str, str]],
    log: Logger | None = None,
    config: AppConfig | None = None,
) -> FolderCompareSummary:
    left = Path(left_dir).expanduser().resolve()
    right = Path(right_dir).expanduser().resolve()
    output = _normalize_output_dir(Path(output_dir).expanduser().resolve())
    logger = log or (lambda message: None)
    app_config = config or load_app_config()

    _validate_folder(left, "Folder bên trái")
    _validate_folder(right, "Folder bên phải")
    output.mkdir(parents=True, exist_ok=True)

    logger(f"Folder bên trái: {left}")
    logger(f"Folder bên phải: {right}")
    logger(f"Folder xuất file compare: {output}")

    fixme_entries: list[WorkbookFixmeEntry] = []
    output_paths: list[Path] = []
    used_output_names: set[str] = set()
    sheet_count = 0
    workbook_count = 0
    for index, pair in enumerate(pairs, start=1):
        left_name = str(pair.get("left_name", "")).strip()
        right_name = str(pair.get("right_name", "")).strip()
        output_name = _unique_output_name(
            _safe_output_name(str(pair.get("output_name", "")).strip(), left_name, right_name, index),
            used_output_names,
        )
        if not left_name and not right_name:
            continue
        left_csv = _resolve_child_csv(left, left_name) if left_name else output / "__missing_left__.csv"
        right_csv = _resolve_child_csv(right, right_name) if right_name else output / "__missing_right__.csv"
        result = write_compare_workbook_for_pairs(
            [(left_csv, right_csv, (right_name or left_name))],
            output / output_name,
            excel_headers=excel_headers_for_workflow(app_config, WORKFLOW_AFTER_HTC_VS_HTM),
            case_folder_name=f"{left.name} - {right.name}",
        )
        workbook_count += 1
        output_paths.append(result.output_path)
        sheet_count += result.sheet_count
        fixme_entries.extend(result.fixme_entries)
        logger(f"Đã tạo {result.output_path.name} từ {left_name or '(trống)'} / {right_name or '(trống)'}.")

    if workbook_count == 0:
        raise ValueError("Chưa có pair CSV nào để xuất compare.")

    return FolderCompareSummary(
        left_dir=left,
        right_dir=right,
        output_path=output,
        sheet_count=sheet_count,
        workbook_count=workbook_count,
        output_paths=output_paths,
        fixme_entries=fixme_entries,
    )


def compare_csv_folder_pairs_to_workbook(
    left_dir: str | Path,
    right_dir: str | Path,
    output_path: str | Path,
    pairs: list[dict[str, str]],
    log: Logger | None = None,
    config: AppConfig | None = None,
) -> FolderCompareSummary:
    left = Path(left_dir).expanduser().resolve()
    right = Path(right_dir).expanduser().resolve()
    output = _normalize_output_path(Path(output_path).expanduser().resolve())
    logger = log or (lambda message: None)
    app_config = config or load_app_config()

    _validate_folder(left, "Folder bÃªn trÃ¡i")
    _validate_folder(right, "Folder bÃªn pháº£i")
    if output.exists() and output.is_dir():
        raise IsADirectoryError(f"File Excel xuáº¥t ra Ä‘ang lÃ  folder: {output}")

    csv_pairs: list[tuple[Path, Path, str]] = []
    for pair in pairs:
        left_name = str(pair.get("left_name", "")).strip()
        right_name = str(pair.get("right_name", "")).strip()
        if not left_name and not right_name:
            continue
        left_csv = _resolve_child_csv(left, left_name) if left_name else output.parent / "__missing_left__.csv"
        right_csv = _resolve_child_csv(right, right_name) if right_name else output.parent / "__missing_right__.csv"
        # The right-side file is the authoritative sheet label for paired export.
        csv_pairs.append((left_csv, right_csv, right_name or left_name))

    if not csv_pairs:
        raise ValueError("ChÆ°a cÃ³ pair CSV nÃ o Ä‘á»ƒ xuáº¥t compare.")

    logger(f"Folder bÃªn trÃ¡i: {left}")
    logger(f"Folder bÃªn pháº£i: {right}")
    logger(f"File Excel gá»™p: {output}")
    result = write_compare_workbook_for_pairs(
        csv_pairs,
        output,
        excel_headers=excel_headers_for_workflow(app_config, WORKFLOW_AFTER_HTC_VS_HTM),
        case_folder_name=f"{left.name} - {right.name}",
    )
    logger(
        f"ÄÃ£ táº¡o {result.output_path.name} "
        f"({result.sheet_count} sheet, {len(result.fixme_entries)} má»¥c FIXME)."
    )
    return FolderCompareSummary(
        left_dir=left,
        right_dir=right,
        output_path=result.output_path,
        sheet_count=result.sheet_count,
        workbook_count=1,
        output_paths=[result.output_path],
        fixme_entries=result.fixme_entries,
    )


def _validate_folder(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} không tồn tại: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} không phải là folder: {path}")


def _normalize_output_path(output_path: Path) -> Path:
    if output_path.suffix.lower() != ".xlsx":
        return output_path.with_suffix(".xlsx")
    return output_path


def _normalize_output_dir(output_path: Path) -> Path:
    if output_path.suffix.lower() == ".xlsx":
        return output_path.with_suffix("")
    return output_path


def _default_pairs(left: Path, right: Path) -> list[FolderComparePair]:
    left_files = _csv_file_names(left)
    right_files = _csv_file_names(right)
    unused_left = list(left_files)
    unused_right = list(right_files)
    pairs: list[FolderComparePair] = []

    right_lookup = {name.casefold(): name for name in right_files}
    for left_name in left_files:
        right_name = right_lookup.get(left_name.casefold())
        if right_name is None:
            continue
        pairs.append(FolderComparePair(left_name, right_name, _default_output_name(left_name, right_name)))
        unused_left.remove(left_name)
        unused_right.remove(right_name)

    for index in range(max(len(unused_left), len(unused_right))):
        left_name = unused_left[index] if index < len(unused_left) else ""
        right_name = unused_right[index] if index < len(unused_right) else ""
        pairs.append(FolderComparePair(left_name, right_name, _default_output_name(left_name, right_name)))
    return pairs


def _csv_file_names(folder: Path) -> list[str]:
    return sorted((path.name for path in folder.glob("*.csv") if path.is_file()), key=str.casefold)


def _resolve_child_csv(folder: Path, file_name: str) -> Path:
    if not file_name.lower().endswith(".csv"):
        raise ValueError(f"File không phải CSV: {file_name}")
    candidate = (folder / file_name).resolve()
    if candidate.parent != folder:
        raise ValueError(f"Tên file CSV không hợp lệ: {file_name}")
    return candidate


def _default_output_name(left_name: str, right_name: str) -> str:
    source = right_name or left_name or "compare"
    return f"{Path(source).stem}.xlsx"


def _safe_output_name(output_name: str, left_name: str, right_name: str, index: int) -> str:
    name = output_name or _default_output_name(left_name, right_name) or f"compare_{index}.xlsx"
    if not name.lower().endswith(".xlsx"):
        name = f"{name}.xlsx"
    return Path(name).name


def _unique_output_name(output_name: str, used_names: set[str]) -> str:
    stem = Path(output_name).stem
    suffix = Path(output_name).suffix or ".xlsx"
    candidate = f"{stem}{suffix}"
    index = 1
    while candidate.casefold() in used_names:
        candidate = f"{stem}_{index}{suffix}"
        index += 1
    used_names.add(candidate.casefold())
    return candidate
