from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Border, Side

    from autocompare_tool.sql_excel_loader import load_sql_entries_from_excel, render_raw_sql_entries
except ImportError:  # pragma: no cover
    Workbook = None
    Border = None
    Side = None
    load_sql_entries_from_excel = None
    render_raw_sql_entries = None


@unittest.skipIf(Workbook is None, "openpyxl is not installed")
class SqlExcelLoaderTests(unittest.TestCase):
    def test_loads_numbered_sql_from_column_b_and_later_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sql.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "SQLList"
            sheet["A5"] = 1
            sheet["B5"] = "select"
            sheet["C5"] = "*"
            sheet["D5"] = "from customers"
            sheet["B6"] = "where id = 1"
            sheet["A10"] = 2
            sheet["B10"] = "select * from orders"
            sheet["B11"] = "where customer_id = 1"
            workbook.save(path)

            entries = load_sql_entries_from_excel(path, "SQLList")

            self.assertEqual(["1", "2"], [entry.number for entry in entries])
            self.assertEqual("select * from customers\nwhere id = 1", entries[0].sql_text)
            self.assertEqual("select * from orders\nwhere customer_id = 1", entries[1].sql_text)
            self.assertIn("-- SQL No.1", render_raw_sql_entries(entries))

    def test_border_can_end_last_sql_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sql.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "SQLList"
            sheet["A1"] = 1
            sheet["B1"] = "select *"
            sheet["B2"] = "from customers"
            border = Border(bottom=Side(style="thin"))
            sheet["A2"].border = border
            sheet["B2"].border = border
            sheet["B4"] = "không thuộc SQL"
            workbook.save(path)

            entries = load_sql_entries_from_excel(path, "SQLList")

            self.assertEqual("select *\nfrom customers", entries[0].sql_text)


if __name__ == "__main__":
    unittest.main()
