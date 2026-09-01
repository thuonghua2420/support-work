from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from openpyxl import Workbook, load_workbook

    from autocompare_tool.compare_workbook_view import (
        CompareWorkbookReference,
        build_compare_view_index,
        read_compare_sheet,
    )
    from autocompare_tool.app_config import ExcelHeaderConfig
    from autocompare_tool.excel_writer import write_compare_workbook_with_fixmes
except ImportError:  # pragma: no cover - optional dependency guard for minimal environments.
    Workbook = None
    load_workbook = None
    CompareWorkbookReference = None
    build_compare_view_index = None
    read_compare_sheet = None
    ExcelHeaderConfig = None
    write_compare_workbook_with_fixmes = None


@unittest.skipIf(load_workbook is None, "openpyxl is not installed")
class CompareWorkbookViewTests(unittest.TestCase):
    def test_index_and_sheet_snapshot_include_excel_style_and_fixme_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            _write_text(before / "table.csv", "id,name,only_before\n1,before,x\n")
            _write_text(after / "table.csv", "id,name,only_after\n1,after,y\n")
            output = root / "compare.xlsx"
            headers = ExcelHeaderConfig(
                "Diff",
                "Before column",
                "After column",
                "Before",
                "After",
                "FIXME",
                "No CSV",
            )

            write_result = write_compare_workbook_with_fixmes(
                before,
                after,
                output,
                excel_headers=headers,
                case_folder_name="UT01",
                include_left_only_files=True,
            )
            reference = CompareWorkbookReference("UT01", output, output.name)

            index = build_compare_view_index([reference])
            sheet = read_compare_sheet(reference, "table", write_result.fixme_entries)

        self.assertEqual("UT01", index["cases"][0]["name"])
        self.assertEqual("compare.xlsx", index["cases"][0]["workbooks"][0]["name"])
        self.assertEqual([{"name": "table"}], index["cases"][0]["workbooks"][0]["sheets"])
        self.assertEqual("table", sheet["sheet_name"])
        self.assertEqual("A", sheet["column_letters"][0])
        self.assertEqual("Diff", sheet["rows"][0]["cells"][0]["value"])
        self.assertEqual("#FFC7CE", sheet["rows"][0]["cells"][0]["style"]["background"])
        self.assertEqual("#9C0006", sheet["rows"][0]["cells"][0]["style"]["color"])
        self.assertEqual("#C6EFCE", sheet["rows"][1]["cells"][0]["style"]["background"])
        self.assertEqual("#000000", sheet["rows"][1]["cells"][0]["style"]["color"])
        self.assertEqual({"background", "color"}, set(sheet["rows"][1]["cells"][0]["style"]))
        self.assertEqual("#E2EFDA", sheet["rows"][2]["cells"][0]["style"]["background"])
        self.assertTrue(
            any(
                cell["style"]["background"] == "#E5CCFF" and cell["style"]["color"] == "#9C0006"
                for row in sheet["rows"]
                for cell in row["cells"]
            )
        )
        self.assertTrue(any(cell["fixme_indices"] for row in sheet["rows"] for cell in row["cells"]))

    def test_sheet_snapshot_resolves_theme_font_colors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "theme.xlsx"
            workbook = Workbook()
            workbook.active.title = "Theme"
            workbook.active["C3"] = "Default theme text"
            workbook.save(output)
            reference = CompareWorkbookReference("UT01", output, output.name)

            sheet = read_compare_sheet(reference, "Theme", [])

        self.assertEqual("#000000", sheet["rows"][2]["cells"][2]["style"]["color"])


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="")


if __name__ == "__main__":
    unittest.main()
