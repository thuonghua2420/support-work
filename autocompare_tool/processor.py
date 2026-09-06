from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .app_config import (
    AppConfig,
    CompareWorkflowConfig,
    default_selected_workflow_keys,
    load_app_config,
    WORKFLOW_HTM_BEFORE_AFTER,
    WORKFLOW_HTC_BEFORE_AFTER,
)
from .excel_writer import WorkbookFixmeEntry, write_compare_workbook_with_fixmes
from .update_compare import filter_update_before_folder

Logger = Callable[[str], None]


@dataclass(frozen=True)
class WorkbookResult:
    output_path: Path
    sheet_count: int
    workflow_key: str
    workflow_label: str
    fixme_entries: list[WorkbookFixmeEntry] = field(default_factory=list)


@dataclass
class TestCaseResult:
    case_path: Path
    copied_files: int = 0
    workbooks: list[WorkbookResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ProcessSummary:
    root_path: Path
    test_cases: list[TestCaseResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def processed_count(self) -> int:
        return len(self.test_cases)

    @property
    def fixme_entries(self) -> list[WorkbookFixmeEntry]:
        entries: list[WorkbookFixmeEntry] = []
        for test_case in self.test_cases:
            for workbook in test_case.workbooks:
                entries.extend(workbook.fixme_entries)
        return entries


def process_root(
    root_path: str | Path,
    log: Logger | None = None,
    selected_workflow_keys: set[str] | list[str] | tuple[str, ...] | None = None,
    config: AppConfig | None = None,
) -> ProcessSummary:
    root = Path(root_path).expanduser().resolve()
    logger = log or (lambda message: None)
    app_config = config or load_app_config()
    selected_keys = set(selected_workflow_keys) if selected_workflow_keys is not None else default_selected_workflow_keys(app_config)

    if not root.exists():
        raise FileNotFoundError(f"Thư mục gốc không tồn tại: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Đường dẫn gốc không phải là thư mục: {root}")
    if not selected_keys:
        raise ValueError("Vui lòng chọn ít nhất một luồng so sánh.")
    workflow_keys = {workflow.key for workflow in app_config.compare_workflows}
    unknown_keys = selected_keys - workflow_keys
    if unknown_keys:
        raise ValueError("Luồng so sánh không hợp lệ: " + ", ".join(sorted(unknown_keys)))

    summary = ProcessSummary(root_path=root)
    test_cases = discover_test_cases(root)
    if not test_cases:
        message = f"Không tìm thấy folder case test UT* bên dưới: {root}"
        summary.errors.append(message)
        logger(message)
        return summary

    logger(f"Tìm thấy {len(test_cases)} folder case test.")
    for case_path in test_cases:
        result = _process_test_case(case_path, logger, app_config, selected_keys)
        summary.test_cases.append(result)
        summary.errors.extend(result.errors)

    logger("Hoàn tất.")
    return summary


def discover_test_cases(root: Path) -> list[Path]:
    if _is_test_case_dir(root):
        return [root]

    return sorted(
        [child for child in root.iterdir() if _is_test_case_dir(child)],
        key=lambda path: path.name.lower(),
    )


def _is_test_case_dir(path: Path) -> bool:
    return path.is_dir() and path.name.upper().startswith("UT")


def _process_test_case(
    case_path: Path,
    log: Logger,
    config: AppConfig,
    selected_workflow_keys: set[str],
) -> TestCaseResult:
    result = TestCaseResult(case_path=case_path)
    log(f"[{case_path.name}] Bắt đầu")

    folders = config.folders
    input_dir = case_path / folders.input_dir
    output_dir = case_path / folders.output_dir
    before_htm = output_dir / folders.before_htm_dir
    before_htc = output_dir / folders.before_htc_dir
    after_htm = output_dir / folders.after_htm_dir
    after_htc = output_dir / folders.after_htc_dir
    compare_dir = output_dir / folders.compare_dir

    try:
        if not input_dir.exists() or not input_dir.is_dir():
            raise FileNotFoundError(f"Thiếu folder Input: {input_dir}")

        for folder in (before_htm, before_htc, compare_dir):
            folder.mkdir(parents=True, exist_ok=True)

        removed_outputs = _remove_unselected_compare_outputs(compare_dir, config.compare_workflows, selected_workflow_keys)
        if removed_outputs:
            log(f"[{case_path.name}] Đã xóa {len(removed_outputs)} file Excel compare không được chọn.")

        copied_files = _refresh_before_folders(
            input_dir,
            before_htm,
            before_htc,
            after_htm,
            after_htc,
        )
        result.copied_files = copied_files
        log(f"[{case_path.name}] Đã sao chép {copied_files} file CSV vào các folder before.")

        for workflow in config.compare_workflows:
            if workflow.key not in selected_workflow_keys:
                continue
            aligned_before_files: set[Path] = set()
            if workflow.key in {WORKFLOW_HTM_BEFORE_AFTER, WORKFLOW_HTC_BEFORE_AFTER}:
                # A failed validation must not leave an old successful workbook visible.
                (compare_dir / workflow.output_file_name).unlink(missing_ok=True)
                try:
                    aligned_before_files = filter_update_before_folder(
                        output_dir / workflow.left_dir_name,
                        output_dir / workflow.right_dir_name,
                        config.update_compare_keys,
                        log,
                        strict=False,
                    )
                except Exception as exc:
                    message = f"[{case_path.name}/{workflow.key}] ERROR: {exc}"
                    result.errors.append(message)
                    log(message)
                    continue
            workbook_result = _write_workflow_workbook(
                case_path,
                output_dir,
                compare_dir,
                workflow,
                config,
                aligned_before_files,
            )
            result.workbooks.append(workbook_result)
            log(
                f"[{case_path.name}] Đã tạo {workbook_result.output_path.name} "
                f"({workbook_result.sheet_count} sheet, {len(workbook_result.fixme_entries)} mục FIXME)."
            )
    except Exception as exc:
        message = f"[{case_path.name}] LỖI: {exc}"
        result.errors.append(message)
        log(message)

    return result


def _remove_unselected_compare_outputs(
    compare_dir: Path,
    workflows: tuple[CompareWorkflowConfig, ...],
    selected_workflow_keys: set[str],
) -> list[Path]:
    removed_outputs: list[Path] = []
    for workflow in workflows:
        if workflow.key in selected_workflow_keys:
            continue
        output_path = compare_dir / workflow.output_file_name
        if output_path.is_file():
            output_path.unlink()
            removed_outputs.append(output_path)
    return removed_outputs


def _write_workflow_workbook(
    case_path: Path,
    output_dir: Path,
    compare_dir: Path,
    workflow: CompareWorkflowConfig,
    config: AppConfig,
    aligned_before_files: set[Path],
) -> WorkbookResult:
    left_dir = output_dir / workflow.left_dir_name
    right_dir = output_dir / workflow.right_dir_name
    output_path = compare_dir / workflow.output_file_name

    write_result = write_compare_workbook_with_fixmes(
        left_dir,
        right_dir,
        output_path,
        excel_headers=config.excel_headers,
        case_folder_name=case_path.name,
        include_left_only_files=workflow.include_left_only_files,
        aligned_before_files=aligned_before_files,
    )
    return WorkbookResult(
        output_path=write_result.output_path,
        sheet_count=write_result.sheet_count,
        workflow_key=workflow.key,
        workflow_label=workflow.label,
        fixme_entries=write_result.fixme_entries,
    )


def _refresh_before_folders(
    input_dir: Path,
    before_new: Path,
    before_current: Path,
    after_new: Path,
    after_current: Path,
) -> int:
    for before_dir in (before_new, before_current):
        _clear_csv_files(before_dir)

    input_csv_files = sorted(input_dir.glob("*.csv"), key=lambda path: path.name.lower())
    for source in input_csv_files:
        shutil.copy2(source, before_new / source.name)
        shutil.copy2(source, before_current / source.name)

    _prune_before_files(before_new, after_new)
    _prune_before_files(before_current, after_current)

    return len(input_csv_files)


def _clear_csv_files(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for csv_file in folder.glob("*.csv"):
        if csv_file.is_file():
            csv_file.unlink()


def _prune_before_files(before_dir: Path, after_dir: Path) -> None:
    after_names = {path.name for path in after_dir.glob("*.csv")} if after_dir.exists() else set()
    for csv_file in before_dir.glob("*.csv"):
        if csv_file.name not in after_names:
            csv_file.unlink()
