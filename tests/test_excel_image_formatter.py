from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from autocompare_tool.excel_image_formatter import (
    _included_row_segments,
    _retry_com_call,
    format_excel_images,
)


class _FakeFont:
    def __init__(self, name: str = "Arial", size: float = 9) -> None:
        self.Name = name
        self.Size = size


class _FakeCell:
    def __init__(self, row: int, column: int, value=None) -> None:
        self.Row = row
        self.Column = column
        self.Value2 = value
        self.Address = f"${_column_name(column)}${row}"
        self.Font = _FakeFont()


class _FakeRange:
    def __init__(self, cell: _FakeCell | None = None) -> None:
        self.selected = False
        self._cell = cell or _FakeCell(1, 1)
        self.Font = self._cell.Font

    @property
    def Row(self) -> int:
        return self._cell.Row

    @property
    def Value2(self):
        return self._cell.Value2

    @property
    def Address(self) -> str:
        return self._cell.Address

    def Select(self) -> None:
        self.selected = True


class _FakeShapes:
    def __init__(self, count: int) -> None:
        self.Count = count


class _FakeCount:
    def __init__(self, count: int) -> None:
        self.Count = count


class _FakeCellCollection:
    def __init__(self, cells: dict[tuple[int, int], _FakeCell]) -> None:
        self._cells = cells
        self.Count = len(cells)

    def Item(self, first: int, second: int | None = None) -> _FakeCell:
        if second is not None:
            return self._cells.setdefault((first, second), _FakeCell(first, second))
        return list(self._cells.values())[first - 1]


class _FakeUsedRange:
    def __init__(self, cells: dict[tuple[int, int], _FakeCell], row_count: int, column_count: int) -> None:
        self.Row = 1
        self.Column = 1
        self.Rows = _FakeCount(row_count)
        self.Columns = _FakeCount(column_count)
        self.Cells = _FakeCellCollection(cells)
        self.Font = _FakeFont()
        self._matches: list[_FakeCell] = []
        self._match_index = 0

    def Find(self, **kwargs):
        expected = _unescape_excel_find(str(kwargs["What"])).casefold()
        self._matches = [
            cell
            for cell in self._cells_in_order()
            if cell.Value2 is not None and str(cell.Value2).strip().casefold() == expected
        ]
        self._match_index = 0
        return self._matches[0] if self._matches else None

    def FindNext(self, **_kwargs):
        if not self._matches:
            return None
        self._match_index = (self._match_index + 1) % len(self._matches)
        return self._matches[self._match_index]

    def _cells_in_order(self) -> list[_FakeCell]:
        return [self.Cells._cells[key] for key in sorted(self.Cells._cells)]


class _FakeTargetRange:
    def __init__(self, start: _FakeCell, end: _FakeCell, sheet) -> None:
        self.Font = _FakeFont()
        self._start = start
        self._end = end
        self._sheet = sheet

    def record_size(self) -> None:
        self._sheet.size_segments.append((self._start.Row, self._end.Row, self.Font.Size))


class _FakeSheet:
    def __init__(self, name: str, shape_count: int, values: dict[str, object] | None = None) -> None:
        self.Name = name
        self.Shapes = _FakeShapes(shape_count)
        self.activated = False
        self.activation_count = 0
        self.size_segments: list[tuple[int, int, float]] = []
        raw_values = values or {"A1": "data", "A2": "more", "A3": "end"}
        cells = {
            _address_parts(address): _FakeCell(*_address_parts(address), value)
            for address, value in raw_values.items()
        }
        max_row = max((row for row, _column in cells), default=1)
        max_column = max((column for _row, column in cells), default=1)
        for row in range(1, max_row + 1):
            for column in range(1, max_column + 1):
                cells.setdefault((row, column), _FakeCell(row, column))
        self.Cells = _FakeCellCollection(cells)
        self.UsedRange = _FakeUsedRange(cells, max_row, max_column)
        self._ranges: dict[str, _FakeRange] = {
            _normalized_address(address): _FakeRange(cell) for address, cell in self._address_cells(cells).items()
        }

    def Activate(self) -> None:
        self.activated = True
        self.activation_count += 1

    def Range(self, first, second=None):
        if second is not None:
            target = _FakeTargetRange(first, second, self)
            font = target.Font

            class _RecordingFont:
                @property
                def Name(self):
                    return font.Name

                @Name.setter
                def Name(self, value):
                    font.Name = value

                @property
                def Size(self):
                    return font.Size

                @Size.setter
                def Size(self, value):
                    font.Size = value
                    target.record_size()

            target.Font = _RecordingFont()
            return target
        address = _normalized_address(str(first))
        if address not in self._ranges:
            row, column = _address_parts(address)
            cell = self.Cells.Item(row, column)
            self._ranges[address] = _FakeRange(cell)
        return self._ranges[address]

    @staticmethod
    def _address_cells(cells):
        return {f"{_column_name(column)}{row}": cell for (row, column), cell in cells.items()}


class _FakeWorksheets:
    def __init__(self, sheets: list[_FakeSheet]) -> None:
        self._sheets = sheets
        self.Count = len(sheets)

    def Item(self, index: int) -> _FakeSheet:
        return self._sheets[index - 1]


class _FakeWorkbook:
    def __init__(self, path: str, sheets: list[_FakeSheet]) -> None:
        self.Name = Path(path).name
        self.Worksheets = _FakeWorksheets(sheets)
        self.saved = False
        self.closed = False
        self.close_save_changes = None

    def Save(self) -> None:
        self.saved = True

    def Close(self, *, SaveChanges: bool) -> None:
        self.closed = True
        self.close_save_changes = SaveChanges


class _FakeWorkbooks:
    def __init__(self, sheet_factory) -> None:
        self._sheet_factory = sheet_factory
        self.opened: list[tuple[str, dict, _FakeWorkbook]] = []

    def Open(self, **kwargs) -> _FakeWorkbook:
        workbook = _FakeWorkbook(kwargs["Filename"], self._sheet_factory())
        self.opened.append((kwargs["Filename"], kwargs, workbook))
        return workbook


class _FakeWindow:
    def __init__(self) -> None:
        self.ScrollRow = 99
        self.ScrollColumn = 99


class _FakeExcel:
    def __init__(self, sheet_factory) -> None:
        self.Workbooks = _FakeWorkbooks(sheet_factory)
        self.ActiveWindow = _FakeWindow()
        self.run_calls: list[tuple[str, bool]] = []
        self.run_error: Exception | None = None

    def Run(self, macro_name: str, draw_format: bool) -> None:
        if self.run_error is not None:
            raise self.run_error
        self.run_calls.append((macro_name, draw_format))


def _column_name(column: int) -> str:
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _address_parts(address: str) -> tuple[int, int]:
    normalized = _normalized_address(address)
    letters = "".join(character for character in normalized if character.isalpha())
    numbers = "".join(character for character in normalized if character.isdigit())
    column = 0
    for character in letters:
        column = column * 26 + ord(character) - 64
    return int(numbers), column


def _normalized_address(address: str) -> str:
    return address.replace("$", "").upper()


def _unescape_excel_find(value: str) -> str:
    return value.replace("~~", "\0").replace("~*", "*").replace("~?", "?").replace("\0", "~")


class ExcelImageFormatterTests(unittest.TestCase):
    def test_retries_when_excel_temporarily_rejects_com_call(self) -> None:
        attempts = 0

        class BusyError(Exception):
            hresult = -2147418111

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise BusyError("Excel is busy")
            return "ready"

        with patch("autocompare_tool.excel_image_formatter.time.sleep") as sleep_mock:
            self.assertEqual("ready", _retry_com_call(operation))

        self.assertEqual(3, attempts)
        self.assertEqual(2, sleep_mock.call_count)

    def test_formats_macro_workbooks_in_safe_copy_and_skips_special_sheets(self) -> None:
        sheets = lambda: [
            _FakeSheet("UT01", 4),
            _FakeSheet("変更履歴", 2),
            _FakeSheet("サンプル補足", 1),
        ]
        excel = _FakeExcel(sheets)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "case-a"
            nested.mkdir()
            source = nested / "report.xlsm"
            source.write_bytes(b"macro workbook")
            (root / "ignored.txt").write_bytes(b"not excel")
            (root / "~$report.xlsm").write_bytes(b"lock")
            previous_output = root / "Formatted" / "old.xlsm"
            previous_output.parent.mkdir()
            previous_output.write_bytes(b"previous")

            with patch(
                "autocompare_tool.excel_image_formatter._excel_application",
                self._excel_context(excel),
            ):
                summary = format_excel_images(root)

            destination = root / "Formatted" / "case-a" / "report.xlsm"
            self.assertEqual(b"macro workbook", destination.read_bytes())

        self.assertEqual(1, summary.file_count)
        self.assertEqual(1, summary.processed_count)
        self.assertEqual(1, summary.sheet_count)
        self.assertEqual(4, summary.shape_count)
        self.assertEqual(2, summary.skipped_sheet_count)
        self.assertEqual(3, summary.workbook_format_sheet_count)
        self.assertEqual(0, summary.error_count)
        self.assertEqual([("'report.xlsm'!FixForMatUTR", True)], excel.run_calls)
        self.assertEqual(1, len(excel.Workbooks.opened))
        opened_path, options, workbook = excel.Workbooks.opened[0]
        self.assertIn("Formatted", opened_path)
        self.assertEqual(0, options["UpdateLinks"])
        self.assertFalse(options["ReadOnly"])
        self.assertTrue(workbook.saved)
        self.assertTrue(workbook.closed)
        self.assertFalse(workbook.close_save_changes)
        self.assertEqual(1, excel.ActiveWindow.ScrollRow)
        self.assertEqual(1, excel.ActiveWindow.ScrollColumn)
        for sheet in workbook.Worksheets._sheets:
            self.assertEqual("Meiryo UI", sheet.UsedRange.Font.Name)
            self.assertEqual(11, sheet.UsedRange.Font.Size)
            self.assertTrue(sheet.Range("A1").selected)

    def test_overwrite_mode_opens_original_workbook(self) -> None:
        excel = _FakeExcel(lambda: [_FakeSheet("UT", 1)])

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.xlsb"
            source.write_bytes(b"xlsb")
            with patch(
                "autocompare_tool.excel_image_formatter._excel_application",
                self._excel_context(excel),
            ):
                summary = format_excel_images(temp_dir, overwrite_original=True, recursive=False)

            self.assertEqual(str(source.resolve()), excel.Workbooks.opened[0][0])

        self.assertIsNone(summary.output_root)
        self.assertEqual(1, summary.processed_count)

    def test_workbook_error_is_reported_and_processing_continues(self) -> None:
        excel = _FakeExcel(lambda: [_FakeSheet("UT", 1)])
        excel.run_error = RuntimeError("macro unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.xlsm"
            source.write_bytes(b"xlsm")
            with patch(
                "autocompare_tool.excel_image_formatter._excel_application",
                self._excel_context(excel),
            ):
                summary = format_excel_images(temp_dir)

        self.assertEqual(0, summary.processed_count)
        self.assertEqual(1, summary.error_count)
        self.assertIn("macro unavailable", summary.errors[0])
        self.assertTrue(excel.Workbooks.opened[0][2].closed)

    def test_formats_xlsx_without_running_vba_macro(self) -> None:
        excel = _FakeExcel(lambda: [_FakeSheet("Sheet1", 0)])

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "plain.xlsx").write_bytes(b"xlsx")
            with patch(
                "autocompare_tool.excel_image_formatter._excel_application",
                self._excel_context(excel),
            ):
                summary = format_excel_images(temp_dir)

        self.assertEqual(1, summary.processed_count)
        self.assertEqual(1, summary.macro_skipped_file_count)
        self.assertEqual(1, summary.workbook_format_sheet_count)
        self.assertEqual([], excel.run_calls)

    def test_applies_font_and_size_except_matching_rows(self) -> None:
        source_sheet = _FakeSheet(
            "UT",
            0,
            values={"A1": "Header", "B2": "Title", "A3": "Body", "B4": "HEADER"},
        )
        excel = _FakeExcel(lambda: [source_sheet])

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "report.xlsm").write_bytes(b"xlsm")
            with patch(
                "autocompare_tool.excel_image_formatter._excel_application",
                self._excel_context(excel),
            ):
                summary = format_excel_images(
                    temp_dir,
                    run_image_format=False,
                    font_name="Calibri",
                    font_size="12.5",
                    font_size_exclusions="Header\n(Title, B2)",
                )

        self.assertEqual("Calibri", source_sheet.UsedRange.Font.Name)
        self.assertEqual([(3, 3, 12.5)], source_sheet.size_segments)
        self.assertEqual(3, summary.font_size_skipped_row_count)
        self.assertEqual(1, summary.workbook_format_sheet_count)
        self.assertTrue(source_sheet.Range("A1").selected)
        self.assertGreaterEqual(source_sheet.activation_count, 2)

    def test_included_row_segments_skip_only_selected_rows(self) -> None:
        self.assertEqual([(2, 3), (5, 6), (8, 8)], _included_row_segments(1, 8, {1, 4, 7}))

    def test_requires_at_least_one_excel_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "plain.txt").write_bytes(b"text")

            with self.assertRaisesRegex(ValueError, "Không tìm thấy workbook Excel"):
                format_excel_images(temp_dir)

    @staticmethod
    def _excel_context(excel):
        @contextmanager
        def context():
            yield excel

        return context


if __name__ == "__main__":
    unittest.main()
