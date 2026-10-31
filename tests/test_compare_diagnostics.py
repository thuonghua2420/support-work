import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from autocompare_tool.app_config import load_app_config
from autocompare_tool.compare_diagnostics import CompareDiagnosticError
from autocompare_tool.csv_table import CsvTable, read_csv_table
from autocompare_tool.dbeaver_csv import read_dbeaver_csv, write_dbeaver_csv
from autocompare_tool.excel_writer import _check_sheet_dimensions, write_compare_workbook_with_fixmes
from autocompare_tool.folder_compare import compare_csv_folders, compare_csv_folder_pairs, compare_csv_folder_pairs_to_workbook
from autocompare_tool.processor import process_root


class CompareDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.left = self.root / "before" / "orders.csv"
        self.right = self.root / "after" / "orders.csv"
        self.output = self.root / "compare.xlsx"
        self.left.parent.mkdir()
        self.right.parent.mkdir()
        self.left.write_bytes(b'id,text\r\n1,"old"\r\n')
        self.right.write_bytes(b'id,text\r\n1,"new"\r\n')

    def compare(self):
        return write_compare_workbook_with_fixmes(self.left.parent, self.right.parent, self.output, case_folder_name="Case01")

    def diagnostic(self, *expected):
        original = {path: path.read_bytes() for path in (self.left, self.right)}
        previous = self.output.read_bytes() if self.output.exists() else None
        with self.assertRaises(CompareDiagnosticError) as raised:
            self.compare()
        message = str(raised.exception)
        for value in (str(self.left), str(self.right), str(self.output), "Case01", "Sheet: orders", *expected):
            self.assertIn(str(value), message)
        self.assertEqual(original, {path: path.read_bytes() for path in original})
        self.assertEqual(previous, self.output.read_bytes() if self.output.exists() else None)
        return message

    def test_long_cell_identifies_side_record_physical_line_column_and_excel_cell(self):
        self.left.write_bytes(('id,text\r\n1,"first\r\nsecond"\r\n2,"' + 'x' * 32768 + '"\r\n').encode())
        self.diagnostic("File CSV: " + str(self.left), "Phía: Trái", "Record CSV: 2", "Dòng vật lý CSV: 4", "Cột CSV: 2",
                        "Tên column: 'text'", "Ô Excel: E4", "32768", "32767")

    def test_long_right_cell_and_long_header_are_identified(self):
        self.right.write_bytes(('id,text\n1,"' + 'x' * 32768 + '"\n').encode())
        self.diagnostic("File CSV: " + str(self.right), "Phía: Phải", "Ô Excel: D4")
        self.right.write_bytes(self.left.read_bytes())
        self.left.write_bytes(('id,' + 'h' * 32768 + '\n1,ok\n').encode())
        message = self.diagnostic("Record CSV: Header", "Cột CSV: 2", "Ô Excel: A5", "32767")
        self.assertLess(len(message), 4000)

    def test_invalid_xml_character_is_reported_without_echoing_entire_value(self):
        self.right.write_bytes(b'id,text\r\n1,"abc\x00def"\r\n')
        self.diagnostic("U+0000", "Vị trí ký tự trong giá trị (từ 1): 4", "File CSV: " + str(self.right), "Ô Excel: D4")

    def test_broken_csv_quote_contains_logical_record_and_physical_range(self):
        self.right.write_bytes(b'id,text\r\n1,"one\r\ntwo\r\n')
        self.diagnostic("thiếu dấu quote", "Record CSV: 1", "Dòng vật lý CSV: 2–4", "Cột CSV: 2", "Tên column: 'text'")

    def test_unexpected_text_after_quote_reports_its_location(self):
        self.right.write_bytes(b'id,text\n1,"ok"oops\n')
        self.diagnostic("sau dấu quote", "Record CSV: 1", "Dòng vật lý CSV: 2", "Cột CSV: 2")

    def test_ragged_rows_report_missing_or_extra_column_and_default_db_reader_stays_compatible(self):
        for row, count in ((b'1\r\n', 1), (b'1,x,extra\r\n', 3)):
            with self.subTest(count=count):
                self.right.write_bytes(b'id,text\r\n' + row)
                self.diagnostic("Số cột header: 2", f"Số cột record: {count}", "Record CSV: 1", "Dòng vật lý CSV: 2")
                self.assertEqual(len(read_dbeaver_csv(self.right).rows), 1)

    def test_duplicate_or_empty_header_is_rejected(self):
        self.right.write_bytes(b'id,id\n1,2\n')
        self.diagnostic("Header CSV trống hoặc trùng", "Cột CSV: 2", "Tên column: 'id'", "Cột trùng trước đó: 1")
        self.right.write_bytes(b'id,\n1,2\n')
        self.diagnostic("Record CSV: Header", "Cột CSV: 2")

    def test_record_limit_is_checked_before_any_sheet_is_written(self):
        self.right.write_bytes(b'id,text\n' + b'1,x\n' * 8191)
        with patch("autocompare_tool.excel_writer._write_sheet") as writer:
            self.diagnostic("8191", "8190", "16384", "Số record trái: 1", "Số record phải: 8191", "Số ô dự kiến")
        writer.assert_not_called()
        allowed = CsvTable(["id"], [{"id": "1"}] * 8190)
        self.assertEqual(_check_sheet_dimensions(allowed, allowed), 3 * 16384)

    def test_excel_row_limit_reports_first_offending_header_without_large_allocation(self):
        self.right.write_bytes(b'id,text,third\n1,x,y\n')
        with patch("autocompare_tool.excel_writer.MAX_ROW", 4):
            self.diagnostic("Giới hạn dòng Excel: 4", "Column đầu tiên vượt giới hạn: 'third'", "Dòng Excel cần: 5")

    def test_header_difference_is_a_warning_and_all_columns_remain_in_workbook(self):
        self.right.write_bytes(b'id,current,extra\n1,new,x\n')
        result = self.compare()
        self.assertEqual(len(result.warnings), 1)
        warning = result.warnings[0]
        for expected in (str(self.left), str(self.right), "Số column trái: 2", "Số column phải: 3", "cột 2: 'text'", "cột 2: 'current'", "cột 3: 'extra'"):
            self.assertIn(expected, warning)
        workbook = load_workbook(self.output)
        self.addCleanup(workbook.close)
        self.assertEqual([workbook.active.cell(row, 1).value for row in range(3, 7)], ["id", None, None, "text"])
        self.assertEqual([workbook.active.cell(row, 2).value for row in range(3, 7)], ["id", "current", "extra", None])

    def test_unknown_failure_is_enriched_with_pair_and_size_context(self):
        with patch("autocompare_tool.excel_writer.build_sheet_comparison", side_effect=MemoryError()):
            self.diagnostic("Loại lỗi: MemoryError", "Không đủ RAM", "Số ô dự kiến sheet: 24", "Cặp CSV: 1/1")

    def test_second_pair_failure_identifies_exact_file_among_many(self):
        (self.left.parent / "second.csv").write_bytes(b'id,text\n1,x,broken\n')
        (self.right.parent / "second.csv").write_bytes(b'id,text\n1,x\n')
        with self.assertRaises(CompareDiagnosticError) as raised:
            self.compare()
        message = str(raised.exception)
        self.assertIn("Cặp CSV: 2/2", message)
        self.assertIn(str(self.left.parent / "second.csv"), message)
        self.assertIn("Sheet: second", message)
        self.assertIn("Số sheet đã xử lý: 1", message)
        self.assertFalse(self.output.exists())

    def test_locked_output_and_full_disk_keep_existing_output(self):
        self.output.write_bytes(b"existing workbook must survive")
        for failure in (PermissionError("file locked"), OSError(errno.ENOSPC, "disk full")):
            with self.subTest(failure=failure):
                with patch("autocompare_tool.excel_writer.Workbook.save", side_effect=failure):
                    with self.assertRaises(CompareDiagnosticError) as raised:
                        self.compare()
                message = str(raised.exception)
                self.assertIn(str(self.output), message)
                self.assertIn("Lưu workbook Excel", message)
                self.assertIn(type(failure).__name__, message)
                self.assertEqual(self.output.read_bytes(), b"existing workbook must survive")
                self.assertEqual(list(self.root.glob("*.xlsx")), [self.output])

    def test_strict_reader_preserves_null_empty_cp932_and_multiline_positions(self):
        self.right.write_bytes('id,text,empty,nullish\r\n1,"日本\r\n語","",\r\n'.encode("cp932"))
        table = read_csv_table(self.right)
        self.assertEqual(table.rows[0], {"id": "1", "text": "日本\r\n語", "empty": "", "nullish": None})
        self.assertEqual(table.line_ranges, [(1, 1), (2, 3)])

    def test_all_folder_export_modes_share_the_same_diagnostics(self):
        self.right.write_bytes(b'id,text\n1,x,y\n')
        pairs = [{"left_name": "orders.csv", "right_name": "orders.csv", "output_name": "orders.xlsx"}]
        for mode in ("single", "separate", "paired_single"):
            with self.subTest(mode=mode), self.assertRaises(CompareDiagnosticError) as raised:
                if mode == "single":
                    compare_csv_folders(self.left.parent, self.right.parent, self.output)
                elif mode == "separate":
                    compare_csv_folder_pairs(self.left.parent, self.right.parent, self.root / "out", pairs)
                else:
                    compare_csv_folder_pairs_to_workbook(self.left.parent, self.right.parent, self.output, pairs)
            self.assertIn(str(self.right), str(raised.exception))

    def test_workflow_error_has_case_workflow_file_column_and_keeps_other_workflows(self):
        config = load_app_config()
        case = self.root / "UT01"
        output = case / config.folders.output_dir
        for folder in (config.folders.before_htm_dir, config.folders.after_htm_dir,
                       config.folders.before_htc_dir, config.folders.after_htc_dir):
            write_dbeaver_csv(output / folder / "orders.csv", ["id", "text"], [["1", "ok"]])
        bad = output / config.folders.before_htm_dir / "orders.csv"
        bad.write_bytes(b'id,text\n1,x,y\n')
        result = process_root(case, config=config, copy_input=False, sort_by_key=False)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.test_cases[0].workbooks), 2)
        for expected in (str(case), str(bad), "htm_before_after", "Luồng compare", "Cột CSV: 3"):
            self.assertIn(expected, result.errors[0])
