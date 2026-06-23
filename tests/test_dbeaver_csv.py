from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocompare_tool.dbeaver_csv import read_dbeaver_csv, write_dbeaver_csv


class DbeaverCsvTests(unittest.TestCase):
    def test_read_distinguishes_null_and_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.csv"
            path.write_text('id,empty_value,null_value,text\n"1","",,"a""b"\n', encoding="utf-8")

            table = read_dbeaver_csv(path)

            self.assertEqual(table.headers, ["id", "empty_value", "null_value", "text"])
            self.assertEqual(table.rows, [["1", "", None, 'a"b']])

    def test_write_quotes_strings_and_leaves_null_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.csv"

            write_dbeaver_csv(path, ["id", "empty_value", "null_value", "text"], [["1", "", None, 'a"b']])

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                'id,empty_value,null_value,text\r\n"1","",,"a""b"\r\n',
            )


if __name__ == "__main__":
    unittest.main()
