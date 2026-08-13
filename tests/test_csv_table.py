from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocompare_tool.compare import cell_value
from autocompare_tool.csv_table import read_csv_table


class CsvTableTests(unittest.TestCase):
    def test_compare_reader_distinguishes_null_and_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.csv"
            path.write_text('id,empty_value,null_value\n"1","",\n', encoding="utf-8")

            table = read_csv_table(path)

            self.assertEqual("", table.rows[0]["empty_value"])
            self.assertIsNone(table.rows[0]["null_value"])
            self.assertEqual("", cell_value(table.rows[0], "empty_value"))
            self.assertEqual("NULL", cell_value(table.rows[0], "null_value"))


if __name__ == "__main__":
    unittest.main()
