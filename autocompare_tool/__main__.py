from __future__ import annotations

import argparse
from pathlib import Path

from .processor import process_root
from .web_app import BUILD_MARKER, DEFAULT_HOST, DEFAULT_PORT, serve


def main() -> int:
    parser = argparse.ArgumentParser(description="Công cụ AutoCompare CSV trước/sau")
    parser.add_argument(
        "root",
        nargs="?",
        help="Thư mục gốc tùy chọn. Nếu truyền giá trị này, chạy compare trực tiếp không mở web.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Địa chỉ bind của web server (mặc định: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port HTTP (mặc định: {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt khi server khởi động")
    parser.add_argument("--desktop", action="store_true", help="Mở giao diện Tkinter cũ")
    args = parser.parse_args()

    if args.desktop:
        from .gui import main as gui_main

        gui_main()
        return 0

    if not args.root:
        print(f"AutoCompare build marker: {BUILD_MARKER}")
        print(f"AutoCompare package path: {Path(__file__).resolve()}")
        serve(args.host, args.port, open_browser=not args.no_browser)
        return 0

    summary = process_root(Path(args.root), log=print)
    return 0 if not summary.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
