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
        self.Left = (column - 1) * 48.0
        self.Top = (row - 1) * 15.0


class _FakeRange:
    def __init__(self, cell: _FakeCell | None = None, *, sheet=None, address: str | None = None) -> None:
        self.selected = False
        self._cell = cell or _FakeCell(1, 1)
        self._sheet = sheet
        self._address = address
        self.Font = self._cell.Font
        self.Interior = _FakeInterior()
        self._borders: dict[int, _FakeBorder] = {}
        self.HorizontalAlignment = None
        self.VerticalAlignment = None
        self.Value = self._cell.Value2
        self.merged = False
        self._matches: list[_FakeCell] = []
        self._match_index = 0

    @property
    def Row(self) -> int:
        return self._cell.Row

    @property
    def Value2(self):
        return self._cell.Value2

    @property
    def Address(self) -> str:
        return self._cell.Address

    @property
    def Width(self) -> float:
        if self._address is None:
            return 48.0
        return _range_width_from_address(self._address)

    def Select(self) -> None:
        self.selected = True

    def Find(self, **kwargs):
        if self._sheet is None:
            return None
        expected = _unescape_excel_find(str(kwargs["What"])).casefold()
        self._matches = [
            cell
            for cell in self._sheet.cells_in_range(self._address or self.Address)
            if cell.Value2 is not None and str(cell.Value2).strip().casefold() == expected
        ]
        self._match_index = 0
        return self._matches[0] if self._matches else None

    def FindNext(self, **_kwargs):
        if not self._matches:
            return None
        self._match_index = (self._match_index + 1) % len(self._matches)
        return self._matches[self._match_index]

    def Borders(self, edge: int):
        return self._borders.setdefault(edge, _FakeBorder())

    def Merge(self) -> None:
        self.merged = True


class _FakeInterior:
    def __init__(self) -> None:
        self.Pattern = None
        self.ThemeColor = None
        self.Color = None
        self.TintAndShade = None
        self.PatternTintAndShade = None


class _FakeBorder:
    def __init__(self) -> None:
        self.LineStyle = None
        self.Weight = None


class _FakeShapes:
    def __init__(self, shapes_or_count) -> None:
        if isinstance(shapes_or_count, int):
            self._shapes = [
                _FakeShape(
                    f"Picture {index}",
                    top_row=3 + (index - 1) * 4,
                    left_column=5 if index % 2 else 20,
                )
                for index in range(1, shapes_or_count + 1)
            ]
        else:
            self._shapes = list(shapes_or_count)

    @property
    def Count(self) -> int:
        return len(self._shapes)

    def Item(self, index: int):
        return self._shapes[index - 1]


class _FakeShape:
    def __init__(
        self,
        name: str,
        *,
        top_row: int,
        left_column: int,
        height_rows: int = 2,
        shape_type: int = 13,
    ) -> None:
        self.Name = name
        self.Type = shape_type
        self._top_row = top_row
        self._left_column = left_column
        self._height_rows = height_rows
        self.Width = 120.0
        self.LockAspectRatio = None

    @property
    def TopLeftCell(self):
        return _FakeCell(self._top_row, self._left_column)

    @property
    def BottomRightCell(self):
        return _FakeCell(self._top_row + self._height_rows - 1, self._left_column)

    @property
    def Left(self) -> float:
        return (self._left_column - 1) * 48.0

    @Left.setter
    def Left(self, value: float) -> None:
        self._left_column = int(value // 48.0) + 1

    @property
    def Top(self) -> float:
        return (self._top_row - 1) * 15.0

    @Top.setter
    def Top(self, value: float) -> None:
        self._top_row = int(value // 15.0) + 1

    @property
    def position(self) -> tuple[int, int]:
        return self._top_row, self._left_column


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
        self.Interior = _FakeInterior()
        self._borders: dict[int, _FakeBorder] = {}

    def record_size(self) -> None:
        self._sheet.size_segments.append((self._start.Row, self._end.Row, self.Font.Size))

    def Borders(self, edge: int):
        border = self._borders.setdefault(edge, _FakeBorder())
        self._sheet.borders.append((self._start.Row, self._start.Column, self._end.Row, self._end.Column, edge, border))
        return border


class _FakeSheet:
    def __init__(self, name: str, shape_count: int | list[_FakeShape], values: dict[str, object] | None = None) -> None:
        self.Name = name
        self.Shapes = _FakeShapes(shape_count)
        self.activated = False
        self.activation_count = 0
        self.size_segments: list[tuple[int, int, float]] = []
        self.inserted_rows: list[tuple[int, int]] = []
        self.borders: list[tuple[int, int, int, int, int, _FakeBorder]] = []
        self.Rows = _FakeRows(self)
        self.Columns = _FakeColumns(self)
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
            _normalized_address(address): _FakeRange(cell, sheet=self, address=_normalized_address(address))
            for address, cell in self._address_cells(cells).items()
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
        if ":" in address:
            return _FakeRange(sheet=self, address=address)
        if address not in self._ranges:
            row, column = _address_parts(address)
            cell = self.Cells.Item(row, column)
            self._ranges[address] = _FakeRange(cell, sheet=self, address=address)
        return self._ranges[address]

    @staticmethod
    def _address_cells(cells):
        return {f"{_column_name(column)}{row}": cell for (row, column), cell in cells.items()}

    def cells_in_range(self, address: str):
        normalized = _normalized_address(address)
        if normalized.endswith(":") or ":" not in normalized:
            return list(self.Cells._cells.values())
        left, right = normalized.split(":", 1)
        if left.isalpha() and right.isalpha():
            start_column = _column_number(left)
            end_column = _column_number(right)
            return [
                cell
                for (row, column), cell in sorted(self.Cells._cells.items())
                if start_column <= column <= end_column
            ]
        if left == right and left.isalpha():
            column = _column_number(left)
            return [cell for (_row, cell_column), cell in sorted(self.Cells._cells.items()) if cell_column == column]
        return list(self.Cells._cells.values())

    def shift_rows(self, start_row: int, count: int) -> None:
        shifted: dict[tuple[int, int], _FakeCell] = {}
        for (row, column), cell in sorted(self.Cells._cells.items()):
            new_row = row + count if row >= start_row else row
            shifted[(new_row, column)] = _FakeCell(new_row, column, cell.Value2)
        self.Cells._cells.clear()
        self.Cells._cells.update(shifted)
        self._ranges.clear()
        for shape in self.Shapes._shapes:
            if shape._top_row >= start_row:
                shape._top_row += count


class _FakeRows:
    def __init__(self, sheet: _FakeSheet) -> None:
        self._sheet = sheet

    def __call__(self, selector):
        return _FakeRowRange(self._sheet, selector)


class _FakeRowRange:
    def __init__(self, sheet: _FakeSheet, selector) -> None:
        self._sheet = sheet
        self._selector = selector
        self.RowHeight = None

    def Insert(self) -> None:
        start_row, end_row = _row_selector_parts(self._selector)
        self._sheet.inserted_rows.append((start_row, end_row))
        self._sheet.shift_rows(start_row, end_row - start_row + 1)


class _FakeColumns:
    def __init__(self, sheet: _FakeSheet) -> None:
        self._sheet = sheet

    def __call__(self, selector):
        return _FakeColumnRange(self._sheet, selector)


class _FakeColumnRange:
    def __init__(self, sheet: _FakeSheet, selector) -> None:
        self._sheet = sheet
        self._selector = selector
        self.ColumnWidth = None


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


def _column_number(column_name: str) -> int:
    number = 0
    for character in column_name:
        number = number * 26 + ord(character.upper()) - 64
    return number


def _range_width_from_address(address: str) -> float:
    normalized = _normalized_address(address)
    if ":" not in normalized:
        return 48.0
    left, right = normalized.split(":", 1)
    left_letters = "".join(character for character in left if character.isalpha())
    right_letters = "".join(character for character in right if character.isalpha())
    if not left_letters or not right_letters:
        return 48.0
    return (_column_number(right_letters) - _column_number(left_letters) + 1) * 48.0


def _row_selector_parts(selector) -> tuple[int, int]:
    text = str(selector)
    if ":" not in text:
        row = int(text)
        return row, row
    start, end = text.split(":", 1)
    return int(start), int(end)


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

    def test_formats_workbooks_with_native_image_layout_and_skips_special_sheets(self) -> None:
        formatted_shapes = [
            _FakeShape("Picture 1", top_row=3, left_column=5),
            _FakeShape("Picture 2", top_row=3, left_column=20),
            _FakeShape("Picture 3", top_row=8, left_column=5),
            _FakeShape("Picture 4", top_row=12, left_column=20),
        ]
        sheets = lambda: [
            _FakeSheet("UT01", formatted_shapes, values={"A1": "Input", "A20": "Steps", "A40": "Output"}),
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
        self.assertEqual([], excel.run_calls)
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
        self.assertEqual((4, 2), formatted_shapes[0].position)
        self.assertEqual((4, 21), formatted_shapes[1].position)
        self.assertEqual((9, 2), formatted_shapes[2].position)
        self.assertEqual((14, 21), formatted_shapes[3].position)
        self.assertEqual(_range_width_from_address("C1:S1"), formatted_shapes[0].Width)
        self.assertEqual(_range_width_from_address("V1:AL1"), formatted_shapes[1].Width)
        self.assertTrue(workbook.Worksheets._sheets[0].borders)
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
        sheets = lambda: [
            _FakeSheet(
                "UT",
                [
                    _FakeShape("Old", top_row=12, left_column=5, height_rows=3),
                    _FakeShape("New", top_row=3, left_column=20, height_rows=20),
                ],
                values={"A1": "Input", "A10": "Steps", "A30": "Output"},
            )
        ]
        excel = _FakeExcel(sheets)

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
        self.assertIn("Input/Steps", summary.errors[0])
        self.assertTrue(excel.Workbooks.opened[0][2].closed)

    def test_formats_xlsx_with_native_image_formatter(self) -> None:
        excel = _FakeExcel(lambda: [_FakeSheet("Sheet1", 0)])

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "plain.xlsx").write_bytes(b"xlsx")
            with patch(
                "autocompare_tool.excel_image_formatter._excel_application",
                self._excel_context(excel),
            ):
                summary = format_excel_images(temp_dir)

        self.assertEqual(1, summary.processed_count)
        self.assertEqual(0, summary.macro_skipped_file_count)
        self.assertEqual(1, summary.workbook_format_sheet_count)
        self.assertEqual([], excel.run_calls)

    def test_inserts_rows_when_resized_image_would_overlap_next_section_marker(self) -> None:
        shape = _FakeShape("Picture Tall", top_row=3, left_column=5, height_rows=20)
        sheet = _FakeSheet("UT", [shape], values={"A1": "Input", "A10": "Steps", "A30": "Output"})
        excel = _FakeExcel(lambda: [sheet])

        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "report.xlsx").write_bytes(b"xlsx")
            with patch(
                "autocompare_tool.excel_image_formatter._excel_application",
                self._excel_context(excel),
            ):
                summary = format_excel_images(temp_dir)

        self.assertEqual(1, summary.shape_count)
        self.assertEqual((4, 2), shape.position)
        self.assertEqual([(10, 25)], sheet.inserted_rows)
        self.assertEqual("Steps", sheet.Cells.Item(26, 1).Value2)

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
