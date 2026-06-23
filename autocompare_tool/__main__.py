from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .gui import main as gui_main
from .processor import process_root


def main() -> int:
    parser = argparse.ArgumentParser(description="AutoCompare CSV before/after tool")
    parser.add_argument(
        "root",
        nargs="?",
        help="Optional root folder. If omitted, the GUI is opened.",
    )
    args = parser.parse_args()

    if not args.root:
        gui_main()
        return 0

    summary = process_root(Path(args.root), log=print)
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
