from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE_NAME = "autocompare_config.ini"

WORKFLOW_HTM_BEFORE_AFTER = "htm_before_after"
WORKFLOW_HTC_BEFORE_AFTER = "htc_before_after"
WORKFLOW_AFTER_HTC_VS_HTM = "after_htc_vs_htm"


@dataclass(frozen=True)
class FolderConfig:
    input_dir: str
    output_dir: str
    compare_dir: str
    before_htm_dir: str
    after_htm_dir: str
    before_htc_dir: str
    after_htc_dir: str


@dataclass(frozen=True)
class WorkbookConfig:
    htm_before_after_file: str
    htc_before_after_file: str
    after_htc_vs_htm_file: str


@dataclass(frozen=True)
class ExcelHeaderConfig:
    diff_count_title: str
    left_column_title: str
    right_column_title: str
    left_record_prefix: str
    right_record_prefix: str
    fixme_text: str
    no_csv_message: str


@dataclass(frozen=True)
class CompareWorkflowConfig:
    key: str
    label: str
    left_dir_name: str
    right_dir_name: str
    output_file_name: str
    default_enabled: bool
    include_left_only_files: bool = False


@dataclass(frozen=True)
class AppConfig:
    folders: FolderConfig
    workbooks: WorkbookConfig
    excel_headers: ExcelHeaderConfig
    compare_workflows: tuple[CompareWorkflowConfig, ...]


def load_app_config(config_path: str | Path | None = None) -> AppConfig:
    path = Path(config_path) if config_path is not None else default_config_path()
    parser = _read_config(path)

    folders = FolderConfig(
        input_dir=_get(parser, "folders", "input_dir", "Input"),
        output_dir=_get(parser, "folders", "output_dir", "Output"),
        compare_dir=_get(parser, "folders", "compare_dir", "Compare"),
        before_htm_dir=_get(parser, "folders", "before_htm_dir", "before新システム出力データ"),
        after_htm_dir=_get(parser, "folders", "after_htm_dir", "after新システム出力データ"),
        before_htc_dir=_get(parser, "folders", "before_htc_dir", "before現行システム出力データ"),
        after_htc_dir=_get(parser, "folders", "after_htc_dir", "after現行システム出力データ"),
    )
    workbooks = WorkbookConfig(
        htm_before_after_file=_get(parser, "workbooks", "htm_before_after_file", "Compare新_Before_After.xlsx"),
        htc_before_after_file=_get(parser, "workbooks", "htc_before_after_file", "Compare現行_Before_After.xlsx"),
        after_htc_vs_htm_file=_get(
            parser,
            "workbooks",
            "after_htc_vs_htm_file",
            "Compare現行_vs_新_After_After.xlsx",
        ),
    )
    excel_headers = ExcelHeaderConfig(
        diff_count_title=_get(parser, "excel_headers", "diff_count_title", "差分行数"),
        left_column_title=_get(parser, "excel_headers", "left_column_title", "前列名"),
        right_column_title=_get(parser, "excel_headers", "right_column_title", "後列名"),
        left_record_prefix=_get(parser, "excel_headers", "left_record_prefix", "前"),
        right_record_prefix=_get(parser, "excel_headers", "right_record_prefix", "後"),
        fixme_text=_get(parser, "excel_headers", "fixme_text", "FIXME"),
        no_csv_message=_get(
            parser,
            "excel_headers",
            "no_csv_message",
            "Không tìm thấy file CSV trong folder so sánh.",
        ),
    )

    workflows = (
        CompareWorkflowConfig(
            key=WORKFLOW_HTM_BEFORE_AFTER,
            label="So sánh trước/sau của HTM",
            left_dir_name=folders.before_htm_dir,
            right_dir_name=folders.after_htm_dir,
            output_file_name=workbooks.htm_before_after_file,
            default_enabled=_get_bool(parser, "compare_workflows", "htm_before_after_enabled", True),
        ),
        CompareWorkflowConfig(
            key=WORKFLOW_HTC_BEFORE_AFTER,
            label="So sánh trước/sau của HTC",
            left_dir_name=folders.before_htc_dir,
            right_dir_name=folders.after_htc_dir,
            output_file_name=workbooks.htc_before_after_file,
            default_enabled=_get_bool(parser, "compare_workflows", "htc_before_after_enabled", True),
        ),
        CompareWorkflowConfig(
            key=WORKFLOW_AFTER_HTC_VS_HTM,
            label="So sánh sau/sau giữa HTC và HTM",
            left_dir_name=folders.after_htc_dir,
            right_dir_name=folders.after_htm_dir,
            output_file_name=workbooks.after_htc_vs_htm_file,
            default_enabled=_get_bool(parser, "compare_workflows", "after_htc_vs_htm_enabled", True),
            include_left_only_files=True,
        ),
    )
    return AppConfig(folders=folders, workbooks=workbooks, excel_headers=excel_headers, compare_workflows=workflows)


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / CONFIG_FILE_NAME


def default_selected_workflow_keys(config: AppConfig) -> set[str]:
    return {workflow.key for workflow in config.compare_workflows if workflow.default_enabled}


def _read_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return parser


def _get(parser: configparser.ConfigParser, section: str, option: str, fallback: str) -> str:
    return parser.get(section, option, fallback=fallback).strip()


def _get_bool(parser: configparser.ConfigParser, section: str, option: str, fallback: bool) -> bool:
    return parser.getboolean(section, option, fallback=fallback)
