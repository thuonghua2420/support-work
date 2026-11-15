from __future__ import annotations

import shutil
from fnmatch import fnmatchcase
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .app_config import (
    AppConfig,
    CompareWorkflowConfig,
    default_selected_workflow_keys,
    excel_headers_for_workflow,
    load_app_config,
    validate_case_pattern,
    WORKFLOW_HTM_BEFORE_AFTER,
    WORKFLOW_HTC_BEFORE_AFTER,
)
from .excel_writer import WorkbookFixmeEntry, write_compare_workbook_with_fixmes
from .csv_order import sort_csv_folders_by_key
from .compare_diagnostics import compare_context, describe_failure

Logger = Callable[[str], None]


@dataclass(frozen=True)
class WorkbookResult:
    output_path: Path
    sheet_count: int
    workflow_key: str
    workflow_label: str
    fixme_entries: list[WorkbookFixmeEntry] = field(default_factory=list)
    removed_equal_before_files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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

    @property
    def warnings(self) -> list[str]:
        return [warning for case in self.test_cases for workbook in case.workbooks for warning in workbook.warnings]


def process_root(
    root_path: str | Path,
    log: Logger | None = None,
    selected_workflow_keys: set[str] | list[str] | tuple[str, ...] | None = None,
    config: AppConfig | None = None,
    *,
    copy_input: bool | None = None,
    sort_by_key: bool | None = None,
    sheet_zoom: int = 85,
) -> ProcessSummary:
    root = Path(root_path).expanduser().resolve()
    logger = log or (lambda message: None)
    app_config = config or load_app_config()
    copy_input = app_config.copy_input_default if copy_input is None else copy_input
    sort_by_key = app_config.sort_by_key_default if sort_by_key is None else sort_by_key
    try:
        if isinstance(sheet_zoom, bool):
            raise ValueError
        if isinstance(sheet_zoom, float) and not sheet_zoom.is_integer():
            raise ValueError
        sheet_zoom = int(sheet_zoom)
    except (TypeError, ValueError) as exc:
        raise ValueError("Zoom sheet phải là số nguyên từ 10 đến 400%.") from exc
    if not 10 <= sheet_zoom <= 400:
        raise ValueError("Zoom sheet phải là số nguyên từ 10 đến 400%.")
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
    test_cases = discover_test_cases(root, app_config.folders.case_pattern, output_dir=app_config.folders.output_dir)
    if not test_cases:
        message = f"Không tìm thấy folder case test khớp mẫu {app_config.folders.case_pattern!r} trong: {root}"
        summary.errors.append(message)
        logger(message)
        return summary

    logger(f"Tìm thấy {len(test_cases)} folder case test.")
    for case_path in test_cases:
        result = _process_test_case(case_path, logger, app_config, selected_keys, copy_input, sort_by_key, sheet_zoom)
        summary.test_cases.append(result)
        summary.errors.extend(result.errors)

    logger("Hoàn tất.")
    return summary


def discover_test_cases(root: Path, case_pattern: str = "UT*", *, output_dir: str | None = None) -> list[Path]:
    pattern = validate_case_pattern(case_pattern)
    root_matches = _is_test_case_dir(root, pattern)
    if root_matches and (output_dir is None or (root / output_dir).is_dir()):
        return [root]

    children = sorted(
        [child for child in root.iterdir() if _is_test_case_dir(child, pattern)],
        key=lambda path: path.name.lower(),
    )
    return children or ([root] if root_matches else [])


def describe_test_cases(
    root_path: str | Path,
    config: AppConfig | None = None,
    *,
    limit: int = 300,
) -> dict:
    """Read-only preview of what ``process_root`` would compare under ``root_path``."""

    root = Path(root_path).expanduser().resolve()
    app_config = config or load_app_config()
    if not root.is_dir():
        raise NotADirectoryError(f"Thư mục gốc không tồn tại: {root}")
    folders = app_config.folders
    cases = discover_test_cases(root, folders.case_pattern, output_dir=folders.output_dir)
    described = []
    for case_path in cases[:limit]:
        output_dir = case_path / folders.output_dir
        input_dir = case_path / folders.input_dir
        workflows = []
        for workflow in app_config.compare_workflows:
            sides = {}
            for side, name in (("left", workflow.left_dir_name), ("right", workflow.right_dir_name)):
                folder = output_dir / name
                sides[side] = {"name": name, "exists": folder.is_dir(), "csv_count": _csv_count(folder)}
            workflows.append({
                "key": workflow.key,
                "ready": sides["left"]["exists"] and sides["right"]["exists"],
                **sides,
            })
        described.append({
            "name": case_path.name,
            "has_input": input_dir.is_dir(),
            "input_count": _csv_count(input_dir),
            "has_output": output_dir.is_dir(),
            "workflows": workflows,
        })
    return {
        "root": str(root),
        "case_pattern": folders.case_pattern,
        "total": len(cases),
        "truncated": len(cases) > limit,
        "workflows": [{"key": item.key, "label": item.label} for item in app_config.compare_workflows],
        "cases": described,
    }


def _csv_count(folder: Path) -> int | None:
    if not folder.is_dir():
        return None
    return sum(1 for child in folder.glob("*.csv") if child.is_file())


def _is_test_case_dir(path: Path, case_pattern: str) -> bool:
    # Only * and ? are wildcards; square brackets are valid literal folder names.
    pattern = case_pattern.casefold().replace("[", "[[]")
    return path.is_dir() and fnmatchcase(path.name.casefold(), pattern)


def _process_test_case(
    case_path: Path,
    log: Logger,
    config: AppConfig,
    selected_workflow_keys: set[str],
    copy_input: bool,
    sort_by_key: bool,
    sheet_zoom: int,
) -> TestCaseResult:
    result = TestCaseResult(case_path=case_path)
    log(f"[{case_path.name}] Bắt đầu")

    folders = config.folders
    input_dir = case_path / folders.input_dir
    output_dir = case_path / folders.output_dir
    before_htm = output_dir / folders.before_htm_dir
    before_htc = output_dir / folders.before_htc_dir
    compare_dir = output_dir / folders.compare_dir

    try:
        copy_failed = False
        if copy_input and selected_workflow_keys & {WORKFLOW_HTM_BEFORE_AFTER, WORKFLOW_HTC_BEFORE_AFTER}:
            try:
                if not input_dir.is_dir():
                    raise FileNotFoundError(f"Thiếu folder Input: {input_dir}")
                result.copied_files = _copy_input_folders(
                    input_dir,
                    before_htm,
                    before_htc,
                    output_dir / folders.after_htm_dir,
                    output_dir / folders.after_htc_dir,
                    selected_workflow_keys,
                )
                log(f"[{case_path.name}] Đã sao chép {result.copied_files} file CSV vào các folder before.")
            except Exception as exc:
                copy_failed = True
                detail = describe_failure(exc, **{"Case": case_path, "Giai đoạn": "Copy CSV từ Input", "Folder Input": input_dir})
                message = f"[{case_path.name}/copy] ERROR:\n{detail}"
                result.errors.append(message)
                log(message)

        for workflow in config.compare_workflows:
            if workflow.key not in selected_workflow_keys:
                continue
            if copy_failed and workflow.key in {WORKFLOW_HTM_BEFORE_AFTER, WORKFLOW_HTC_BEFORE_AFTER}:
                continue
            try:
                folders_to_compare = [output_dir / workflow.left_dir_name, output_dir / workflow.right_dir_name]
                for folder in folders_to_compare:
                    if not folder.is_dir():
                        raise FileNotFoundError(f"Thiếu folder compare: {folder}")
                if sort_by_key:
                    sort_csv_folders_by_key(
                        folders_to_compare, config.update_compare_keys, log, require_keys=True,
                        include_right_only_files=workflow.key not in {
                            WORKFLOW_HTM_BEFORE_AFTER, WORKFLOW_HTC_BEFORE_AFTER,
                        },
                    )
                workbook_result = _write_workflow_workbook(
                    case_path, output_dir, compare_dir, workflow, config, sheet_zoom,
                )
            except Exception as exc:
                detail = describe_failure(exc, **{
                    "Case": case_path, "Luồng compare": workflow.label, "Giai đoạn": "Chuẩn bị luồng compare",
                    "Folder trái": output_dir / workflow.left_dir_name, "Folder phải": output_dir / workflow.right_dir_name,
                    "Workbook": compare_dir / workflow.output_file_name,
                })
                message = f"[{case_path.name}/{workflow.key}] ERROR:\n{detail}"
                result.errors.append(message)
                log(message)
                continue
            result.workbooks.append(workbook_result)
            for warning in workbook_result.warnings:
                log(warning)
            log(
                f"[{case_path.name}] Đã tạo {workbook_result.output_path.name} "
                f"({workbook_result.sheet_count} sheet, {len(workbook_result.fixme_entries)} mục FIXME)."
            )
    except Exception as exc:
        message = f"[{case_path.name}] LỖI:\n{describe_failure(exc, **{'Case': case_path})}"
        result.errors.append(message)
        log(message)

    return result


def _write_workflow_workbook(
    case_path: Path,
    output_dir: Path,
    compare_dir: Path,
    workflow: CompareWorkflowConfig,
    config: AppConfig,
    sheet_zoom: int,
) -> WorkbookResult:
    left_dir = output_dir / workflow.left_dir_name
    right_dir = output_dir / workflow.right_dir_name
    output_path = compare_dir / workflow.output_file_name
    is_update_compare = workflow.key in {WORKFLOW_HTM_BEFORE_AFTER, WORKFLOW_HTC_BEFORE_AFTER}

    write_result = write_compare_workbook_with_fixmes(
        left_dir,
        right_dir,
        output_path,
        excel_headers=excel_headers_for_workflow(config, workflow.key),
        case_folder_name=case_path.name,
        include_left_only_files=is_update_compare or workflow.include_left_only_files,
        include_right_only_files=not is_update_compare,
        sheet_zoom=sheet_zoom,
        key_columns_by_table=config.update_compare_keys,
    )
    return WorkbookResult(
        output_path=write_result.output_path,
        sheet_count=write_result.sheet_count,
        workflow_key=workflow.key,
        workflow_label=workflow.label,
        fixme_entries=write_result.fixme_entries,
        warnings=write_result.warnings,
    )


def _copy_input_folders(
    input_dir: Path,
    before_new: Path,
    before_current: Path,
    after_new: Path,
    after_current: Path,
    selected_workflow_keys: set[str],
) -> int:
    input_csv_files = {path.name.lower(): path for path in input_dir.glob("*.csv")}
    copied_count = 0

    copy_pairs = (
        (WORKFLOW_HTM_BEFORE_AFTER, before_new, after_new),
        (WORKFLOW_HTC_BEFORE_AFTER, before_current, after_current),
    )
    for workflow_key, before_dir, after_dir in copy_pairs:
        if workflow_key not in selected_workflow_keys:
            continue
        if not after_dir.is_dir():
            continue

        after_csv_files = sorted(after_dir.glob("*.csv"), key=lambda path: path.name.lower())
        for after_csv in after_csv_files:
            source = input_csv_files.get(after_csv.name.lower())
            if source is None:
                continue
            with compare_context("Copy CSV từ Input", **{"File CSV": source, "File đích": before_dir / source.name}):
                before_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, before_dir / source.name)
            copied_count += 1

    return copied_count
