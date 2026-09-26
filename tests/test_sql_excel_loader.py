from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Border, Side

    from autocompare_tool.sql_excel_loader import format_excel_sql_entries, load_sql_entries_from_excel, render_raw_sql_entries
except ImportError:  # pragma: no cover
    Workbook = None
    Border = None
    Side = None
    format_excel_sql_entries = None
    load_sql_entries_from_excel = None
    render_raw_sql_entries = None


@unittest.skipIf(Workbook is None, "openpyxl is not installed")
class SqlExcelLoaderTests(unittest.TestCase):
    def test_loads_numbered_sql_from_column_b_and_column_c_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sql.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "SQLList"
            sheet["A5"] = 1
            sheet["B5"] = "select * from customers"
            sheet["C5"] = "lấy danh sách khách hàng"
            sheet["D5"] = "from ignored_table"
            sheet["B6"] = "where id = 1"
            sheet["C6"] = "lọc theo id"
            sheet["A10"] = 2
            sheet["B10"] = "select * from orders"
            sheet["B11"] = "where customer_id = 1"
            workbook.save(path)

            entries = load_sql_entries_from_excel(path, "SQLList")

            self.assertEqual(["1", "2"], [entry.number for entry in entries])
            self.assertEqual("select * from customers\nwhere id = 1", entries[0].sql_text)
            self.assertEqual(2, len(entries[0].sql_lines))
            self.assertEqual("lấy danh sách khách hàng", entries[0].sql_lines[0].note)
            self.assertNotIn("ignored_table", entries[0].sql_text)
            self.assertEqual("select * from orders\nwhere customer_id = 1", entries[1].sql_text)
            raw_sql = render_raw_sql_entries(entries)
            self.assertIn("-- SQL No.1", raw_sql)
            self.assertIn("where id = 1;  -- lọc theo id", raw_sql)
            self.assertIn("select * from customers  -- lấy danh sách khách hàng", raw_sql)

    def test_format_excel_sql_entries_keeps_column_c_notes_as_comments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sql.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "SQLList"
            sheet["A1"] = 1
            sheet["B1"] = "select * from customers"
            sheet["C1"] = "dòng customers"
            sheet["B2"] = "where customer_id = @CustomerId"
            sheet["C2"] = "@CustomerId lấy data từ SQL no.3"
            workbook.save(path)

            entries = load_sql_entries_from_excel(path, "SQLList")
            result = format_excel_sql_entries(entries, dialect="tsql")

            self.assertIn("-- SQL No.1", result.formatted_sql)
            customer_note_line = next(line for line in result.formatted_sql.splitlines() if "-- dòng customers" in line)
            parameter_note_line = next(line for line in result.formatted_sql.splitlines() if "-- @CustomerId lấy data từ SQL no.3" in line)
            self.assertIn("FROM customers", customer_note_line)
            self.assertIn("customer_id = @CustomerId", parameter_note_line)

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

    def test_notes_follow_repeated_column_b_fragments_in_excel_row_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sql.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "SQLList"
            sheet["A1"] = 1
            sheet["B1"] = "select id from customers"
            sheet["C1"] = "customers lần 1"
            sheet["B2"] = "union all"
            sheet["B3"] = "select id from customers"
            sheet["C3"] = "customers lần 2"
            workbook.save(path)

            entries = load_sql_entries_from_excel(path, "SQLList")
            result = format_excel_sql_entries(entries, dialect="tsql")
            note_lines = [line for line in result.formatted_sql.splitlines() if "-- customers lần" in line]

            self.assertEqual(2, len(note_lines))
            self.assertIn("customers lần 1", note_lines[0])
            self.assertIn("customers lần 2", note_lines[1])
            self.assertTrue(all("FROM customers" in line for line in note_lines))


if __name__ == "__main__":
    unittest.main()
