from __future__ import annotations

import configparser
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE_NAME = "autocompare_config.ini"
DEFAULT_EXCEL_COMPARE_MAX_DETAIL_ROWS = 2_000_000

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
    case_pattern: str = "UT*"


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
class ExcelCompareStyleConfig:
    base_font_color: str
    header_font_color: str
    diff_font_color: str
    a1_font_color: str
    fixme_font_color: str
    a1_fill_color: str
    header_fill_color: str
    name_fill_color: str
    diff_fill_color: str


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
    left_group_start_column: int
    left_group_end_column: int
    right_group_start_column: int
    left_anchor_column: int
    right_anchor_column: int
    left_width_range: str
    right_width_range: str
    first_row_height: float
    first_column_width: float
    image_row_padding: int
    image_spacing_pixels: float
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
class DatabaseWorkspaceConfig:
    page_size: int
    max_page_size: int
    query_timeout_seconds: int
    write_mode_timeout_minutes: int
    export_batch_size: int
    workspace_spool_limit_mb: int


@dataclass(frozen=True)
class ExcelCompareConfig:
    max_detail_rows: int = DEFAULT_EXCEL_COMPARE_MAX_DETAIL_ROWS


@dataclass(frozen=True)
class AppConfig:
    folders: FolderConfig
    workbooks: WorkbookConfig
    excel_headers: ExcelHeaderConfig
    excel_headers_by_workflow: dict[str, ExcelHeaderConfig]
    excel_compare_style: ExcelCompareStyleConfig
    compare_workflows: tuple[CompareWorkflowConfig, ...]
    excel_image_format: ExcelImageFormatConfig
    database_workspace: DatabaseWorkspaceConfig
    update_compare_keys: dict[str, tuple[str, ...]] = field(default_factory=dict)
    copy_input_default: bool = False
    sort_by_key_default: bool = False
    multi_database_default: bool = False
    excel_compare: ExcelCompareConfig = field(default_factory=ExcelCompareConfig)


def load_app_config(config_path: str | Path | None = None) -> AppConfig:
    path = Path(config_path) if config_path is not None else default_config_path()
    parser = _read_config(path)

    folders = FolderConfig(
        case_pattern=validate_case_pattern(_get(parser, "folders", "case_pattern", "UT*")),
        input_dir=_get(parser, "folders", "input_dir", "入力データ"),
        output_dir=_get(parser, "folders", "output_dir", "出力（登録・更新）データ"),
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
            "Compare新-現行_After.xlsx",
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
    excel_headers_by_workflow = {
        WORKFLOW_HTM_BEFORE_AFTER: _read_excel_headers(parser, "excel_headers_htm_before_after", excel_headers),
        WORKFLOW_HTC_BEFORE_AFTER: _read_excel_headers(parser, "excel_headers_htc_before_after", excel_headers),
        WORKFLOW_AFTER_HTC_VS_HTM: _read_excel_headers(parser, "excel_headers_after_htc_vs_htm", excel_headers),
    }
    excel_compare_style = ExcelCompareStyleConfig(
        base_font_color=_get_hex_color(parser, "excel_compare_style", "base_font_color", "000000"),
        header_font_color=_get_hex_color(parser, "excel_compare_style", "header_font_color", "006100"),
        diff_font_color=_get_hex_color(parser, "excel_compare_style", "diff_font_color", "FF0000"),
        a1_font_color=_get_hex_color(parser, "excel_compare_style", "a1_font_color", "9C0006"),
        fixme_font_color=_get_hex_color(parser, "excel_compare_style", "fixme_font_color", "000000"),
        a1_fill_color=_get_hex_color(parser, "excel_compare_style", "a1_fill_color", "FFC7CE"),
        header_fill_color=_get_hex_color(parser, "excel_compare_style", "header_fill_color", "C6EFCE"),
        name_fill_color=_get_hex_color(parser, "excel_compare_style", "name_fill_color", "E2EFDA"),
        diff_fill_color=_get_hex_color(parser, "excel_compare_style", "diff_fill_color", "E5CCFF"),
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
        left_group_start_column=_get_int(parser, "excel_image_format", "left_group_start_column", 1),
        left_group_end_column=_get_int(parser, "excel_image_format", "left_group_end_column", 18),
        right_group_start_column=_get_int(parser, "excel_image_format", "right_group_start_column", 19),
        left_anchor_column=_get_int(parser, "excel_image_format", "left_anchor_column", 2),
        right_anchor_column=_get_int(parser, "excel_image_format", "right_anchor_column", 21),
        left_width_range=_get(parser, "excel_image_format", "left_width_range", "C1:S1"),
        right_width_range=_get(parser, "excel_image_format", "right_width_range", "V1:AL1"),
        first_row_height=_get_float(parser, "excel_image_format", "first_row_height", 25.5),
        first_column_width=_get_float(parser, "excel_image_format", "first_column_width", 8.29),
        image_row_padding=_get_int(parser, "excel_image_format", "image_row_padding", 2),
        image_spacing_pixels=_get_float(parser, "excel_image_format", "image_spacing_pixels", 60),
        value_scan_column_count=_get_int(parser, "excel_image_format", "value_scan_column_count", 10),
        draw_borders=_get_bool(parser, "excel_image_format", "draw_borders", True),
        draw_background=_get_bool(parser, "excel_image_format", "draw_background", False),
        draw_header=_get_bool(parser, "excel_image_format", "draw_header", False),
        header_fill_range=_get(parser, "excel_image_format", "header_fill_range", "A1:AJ1"),
        left_header_range=_get(parser, "excel_image_format", "left_header_range", "A1:R1"),
        right_header_range=_get(parser, "excel_image_format", "right_header_range", "S1:AJ1"),
        left_header_text=_get(parser, "excel_image_format", "left_header_text", "現行システム"),
        right_header_text=_get(parser, "excel_image_format", "right_header_text", "新システム"),
        header_fill_color=_get_int(parser, "excel_image_format", "header_fill_color", 11389944),
        header_font_size=_get_float(parser, "excel_image_format", "header_font_size", 22),
        border_start_row=_get_int(parser, "excel_image_format", "border_start_row", 5),
        separator_column=_get_int(parser, "excel_image_format", "separator_column", 20),
        right_border_column=_get_int(parser, "excel_image_format", "right_border_column", 38),
        bottom_border_last_column=_get_int(parser, "excel_image_format", "bottom_border_last_column", 38),
    )
    database_workspace = DatabaseWorkspaceConfig(
        page_size=_get_bounded_int(parser, "database_workspace", "page_size", 100, 1, 500),
        max_page_size=_get_bounded_int(parser, "database_workspace", "max_page_size", 500, 1, 5000),
        query_timeout_seconds=_get_bounded_int(
            parser,
            "database_workspace",
            "query_timeout_seconds",
            120,
            0,
            86400,
        ),
        write_mode_timeout_minutes=_get_bounded_int(
            parser,
            "database_workspace",
            "write_mode_timeout_minutes",
            30,
            1,
            1440,
        ),
        export_batch_size=_get_bounded_int(
            parser,
            "database_workspace",
            "export_batch_size",
            5000,
            100,
            100000,
        ),
        workspace_spool_limit_mb=_get_bounded_int(
            parser,
            "database_workspace",
            "workspace_spool_limit_mb",
            512,
            16,
            10240,
        ),
    )
    try:
        multi_database_default = _get_bool(parser, "database", "multi_database_default", False)
    except ValueError:
        multi_database_default = False
    return AppConfig(
        folders=folders,
        workbooks=workbooks,
        excel_headers=excel_headers,
        excel_headers_by_workflow=excel_headers_by_workflow,
        excel_compare_style=excel_compare_style,
        compare_workflows=workflows,
        excel_image_format=excel_image_format,
        database_workspace=database_workspace,
        update_compare_keys=_read_update_compare_keys(parser),
        copy_input_default=_get_bool(parser, "compare_workflows", "copy_input_enabled", False),
        sort_by_key_default=_get_bool(parser, "compare_workflows", "sort_by_key_enabled", False),
        multi_database_default=multi_database_default,
        excel_compare=ExcelCompareConfig(
            max_detail_rows=_get_bounded_int(
                parser, "excel_compare", "max_detail_rows",
                DEFAULT_EXCEL_COMPARE_MAX_DETAIL_ROWS, 1_000, 20_000_000,
            ),
        ),
    )


def validate_case_pattern(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Mẫu tên case không được để trống.")
    pattern = value.strip()
    if len(pattern) > 255 or pattern in {".", ".."} or pattern.endswith(".") or re.search(r'[<>:"/\\|\x00-\x1f\x7f]', pattern):
        raise ValueError("Mẫu tên case phải là tên thư mục hoặc mẫu tên, không chứa đường dẫn. Có thể dùng * và ?.")
    return pattern


def _read_update_compare_keys(parser: configparser.ConfigParser) -> dict[str, tuple[str, ...]]:
    section = "update_compare_keys"
    if not parser.has_section(section):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for table, raw in parser.items(section):
        columns = tuple(part.strip() for part in raw.split(","))
        if not all(columns) or len(set(columns)) != len(columns):
            raise ValueError(f"[{section}] {table}: key columns must be nonempty and unique.")
        result[table.casefold()] = columns
    return result


def default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / CONFIG_FILE_NAME


def default_selected_workflow_keys(config: AppConfig) -> set[str]:
    return {workflow.key for workflow in config.compare_workflows if workflow.default_enabled}


def excel_headers_for_workflow(config: AppConfig, workflow_key: str) -> ExcelHeaderConfig:
    return config.excel_headers_by_workflow.get(workflow_key, config.excel_headers)


def _read_excel_headers(
    parser: configparser.ConfigParser,
    section: str,
    base: ExcelHeaderConfig | None,
) -> ExcelHeaderConfig:
    return ExcelHeaderConfig(
        diff_count_title=_get(parser, section, "diff_count_title", base.diff_count_title if base else "差分行数"),
        left_column_title=_get(parser, section, "left_column_title", base.left_column_title if base else "前列名"),
        right_column_title=_get(parser, section, "right_column_title", base.right_column_title if base else "後列名"),
        left_record_prefix=_get(parser, section, "left_record_prefix", base.left_record_prefix if base else "前"),
        right_record_prefix=_get(parser, section, "right_record_prefix", base.right_record_prefix if base else "後"),
        fixme_text=_get(parser, section, "fixme_text", base.fixme_text if base else "FIXME"),
        no_csv_message=_get(
            parser,
            section,
            "no_csv_message",
            base.no_csv_message if base else "Không tìm thấy file CSV trong folder so sánh.",
        ),
    )


def _read_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8-sig")
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


def _get_hex_color(parser: configparser.ConfigParser, section: str, option: str, fallback: str) -> str:
    value = _get(parser, section, option, fallback).removeprefix("#").strip().upper()
    if len(value) not in {6, 8}:
        return fallback
    try:
        int(value, 16)
    except ValueError:
        return fallback
    return value


def _get_bounded_int(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    fallback: int,
    minimum: int,
    maximum: int,
) -> int:
    value = _get_int(parser, section, option, fallback)
    if value < minimum or value > maximum:
        return fallback
    return value


def _get_float(parser: configparser.ConfigParser, section: str, option: str, fallback: float) -> float:
    try:
        return parser.getfloat(section, option, fallback=fallback)
    except ValueError:
        return fallback
