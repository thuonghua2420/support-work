from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .gui import main as gui_main
from .processor import process_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Công cụ AutoCompare CSV trước/sau")
    parser.add_argument(
        "root",
        nargs="?",
        help="Thư mục gốc tùy chọn. Nếu bỏ trống, hệ thống sẽ mở giao diện GUI.",
    )
    args = parser.parse_args()

    if not args.root:
        gui_main()
        return 0

    summary = process_root(Path(args.root), log=print)
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
