from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Callable

Logger = Callable[[str], None]


def run_copy_ut_files(source_path: str | Path, target_path: str | Path, log: Logger | None = None) -> Path:
    logger = log or (lambda message: None)
    module = _load_copy_module()

    logger(f"Copy source: {source_path}")
    logger(f"Copy target: {target_path}")
    log_path = module.run(Path(source_path), Path(target_path))
    logger(f"Copy completed. Log file: {log_path}")
    return Path(log_path)


def _load_copy_module() -> ModuleType:
    module_path = Path(__file__).resolve().parent.parent / "copy_ut_files.py"
    if not module_path.exists():
        raise FileNotFoundError(f"copy_ut_files.py not found: {module_path}")

    spec = importlib.util.spec_from_file_location("copy_ut_files", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load copy_ut_files.py: {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "run"):
        raise AttributeError("copy_ut_files.py does not expose run(path1, path2).")

    return module
