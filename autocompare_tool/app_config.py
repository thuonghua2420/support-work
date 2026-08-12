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
    folder_compare_file: str


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
class ExcelImageFormatConfig:
    excluded_sheet_markers: tuple[str, ...]
    shape_name_markers: tuple[str, ...]
    input_marker: str
    steps_marker: str
    output_marker: str
    marker_column: int
    right_group_start_column: int
    left_anchor_column: int
    right_anchor_column: int
    left_width_range: str
    right_width_range: str
    first_row_height: float
    first_column_width: float
    image_row_padding: int
    value_scan_column_count: int
    draw_borders: bool
    draw_background: bool
    draw_header: bool
    header_fill_range: str
    left_header_range: str
    right_header_range: str
    left_header_text: str
    right_header_text: str
    header_fill_color: int
    header_font_size: float
    border_start_row: int
    separator_column: int
    right_border_column: int
    bottom_border_last_column: int


@dataclass(frozen=True)
class AppConfig:
    folders: FolderConfig
    workbooks: WorkbookConfig
    excel_headers: ExcelHeaderConfig
    compare_workflows: tuple[CompareWorkflowConfig, ...]
    excel_image_format: ExcelImageFormatConfig


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
        folder_compare_file=_get(parser, "workbooks", "folder_compare_file", "Compare_2_Folder_CSV.xlsx"),
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
    excel_image_format = ExcelImageFormatConfig(
        excluded_sheet_markers=_get_list(
            parser,
            "excel_image_format",
            "excluded_sheet_markers",
            (
                "変更履歴",
                "サンプル",
                "å¤‰æ›´å±¥æ­´",
                "ã‚µãƒ³ãƒ—ãƒ«",
                "â€¢ÃÂXâ€”Å¡â€”Ã°",
                "Æ’TÆ’â€œÆ’vÆ’â€¹",
            ),
        ),
        shape_name_markers=_get_list(
            parser,
            "excel_image_format",
            "shape_name_markers",
            ("picture", "図", "Â}"),
        ),
        input_marker=_get(parser, "excel_image_format", "input_marker", "Input"),
        steps_marker=_get(parser, "excel_image_format", "steps_marker", "Steps"),
        output_marker=_get(parser, "excel_image_format", "output_marker", "Output"),
        marker_column=_get_int(parser, "excel_image_format", "marker_column", 1),
        right_group_start_column=_get_int(parser, "excel_image_format", "right_group_start_column", 19),
        left_anchor_column=_get_int(parser, "excel_image_format", "left_anchor_column", 2),
        right_anchor_column=_get_int(parser, "excel_image_format", "right_anchor_column", 21),
        left_width_range=_get(parser, "excel_image_format", "left_width_range", "C1:S1"),
        right_width_range=_get(parser, "excel_image_format", "right_width_range", "V1:AL1"),
        first_row_height=_get_float(parser, "excel_image_format", "first_row_height", 25.5),
        first_column_width=_get_float(parser, "excel_image_format", "first_column_width", 8.29),
        image_row_padding=_get_int(parser, "excel_image_format", "image_row_padding", 2),
        value_scan_column_count=_get_int(parser, "excel_image_format", "value_scan_column_count", 10),
        draw_borders=_get_bool(parser, "excel_image_format", "draw_borders", True),
        draw_background=_get_bool(parser, "excel_image_format", "draw_background", False),
        draw_header=_get_bool(parser, "excel_image_format", "draw_header", False),
        header_fill_range=_get(parser, "excel_image_format", "header_fill_range", "A1:AJ1"),
        left_header_range=_get(parser, "excel_image_format", "left_header_range", "A1:R1"),
        right_header_range=_get(parser, "excel_image_format", "right_header_range", "S1:AJ1"),
        left_header_text=_get(parser, "excel_image_format", "left_header_text", "新システム"),
        right_header_text=_get(parser, "excel_image_format", "right_header_text", "現行システム"),
        header_fill_color=_get_int(parser, "excel_image_format", "header_fill_color", 11389944),
        header_font_size=_get_float(parser, "excel_image_format", "header_font_size", 22),
        border_start_row=_get_int(parser, "excel_image_format", "border_start_row", 5),
        separator_column=_get_int(parser, "excel_image_format", "separator_column", 20),
        right_border_column=_get_int(parser, "excel_image_format", "right_border_column", 38),
        bottom_border_last_column=_get_int(parser, "excel_image_format", "bottom_border_last_column", 38),
    )
    return AppConfig(
        folders=folders,
        workbooks=workbooks,
        excel_headers=excel_headers,
        compare_workflows=workflows,
        excel_image_format=excel_image_format,
    )


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


def _get_list(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    if not parser.has_option(section, option):
        return fallback
    raw_value = parser.get(section, option, fallback="")
    values: list[str] = []
    for line in raw_value.splitlines():
        cleaned_line = line.strip()
        if not cleaned_line or cleaned_line.startswith("#"):
            continue
        values.extend(part.strip() for part in cleaned_line.split(",") if part.strip())
    return tuple(values) or fallback


def _get_bool(parser: configparser.ConfigParser, section: str, option: str, fallback: bool) -> bool:
    return parser.getboolean(section, option, fallback=fallback)


def _get_int(parser: configparser.ConfigParser, section: str, option: str, fallback: int) -> int:
    try:
        return parser.getint(section, option, fallback=fallback)
    except ValueError:
        return fallback


def _get_float(parser: configparser.ConfigParser, section: str, option: str, fallback: float) -> float:
    try:
        return parser.getfloat(section, option, fallback=fallback)
    except ValueError:
        return fallback
