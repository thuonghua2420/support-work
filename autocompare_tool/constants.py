from __future__ import annotations

from .app_config import load_app_config

_CONFIG = load_app_config()

INPUT_DIR = _CONFIG.folders.input_dir
OUTPUT_DIR = _CONFIG.folders.output_dir

BEFORE_NEW_DIR = _CONFIG.folders.before_htm_dir
AFTER_NEW_DIR = _CONFIG.folders.after_htm_dir
BEFORE_CURRENT_DIR = _CONFIG.folders.before_htc_dir
AFTER_CURRENT_DIR = _CONFIG.folders.after_htc_dir
COMPARE_DIR = _CONFIG.folders.compare_dir

COMPARE_NEW_FILE = _CONFIG.workbooks.htm_before_after_file
COMPARE_CURRENT_FILE = _CONFIG.workbooks.htc_before_after_file
COMPARE_AFTER_AFTER_FILE = _CONFIG.workbooks.after_htc_vs_htm_file
