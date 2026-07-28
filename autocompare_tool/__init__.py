"""Package của công cụ AutoCompare."""

from __future__ import annotations

__all__ = ["ProcessSummary", "process_root"]


def __getattr__(name: str):
    if name in __all__:
        from .processor import ProcessSummary, process_root

        return {"ProcessSummary": ProcessSummary, "process_root": process_root}[name]

    raise AttributeError(f"module 'autocompare_tool' không có attribute {name!r}")
