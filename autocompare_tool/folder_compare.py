from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .app_config import AppConfig, load_app_config
from .excel_writer import WorkbookFixmeEntry, write_compare_workbook_with_fixmes

Logger = Callable[[str], None]


@dataclass
class FolderCompareSummary:
    left_dir: Path
    right_dir: Path
    output_path: Path
    sheet_count: int = 0
    fixme_entries: list[WorkbookFixmeEntry] = field(default_factory=list)


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
        excel_headers=app_config.excel_headers,
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
