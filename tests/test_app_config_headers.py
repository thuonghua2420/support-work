from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocompare_tool.app_config import (
    WORKFLOW_AFTER_HTC_VS_HTM,
    WORKFLOW_HTC_BEFORE_AFTER,
    WORKFLOW_HTM_BEFORE_AFTER,
    excel_headers_for_workflow,
    load_app_config,
)


class AppConfigHeaderTests(unittest.TestCase):
    def test_multi_database_default_is_opt_in_and_invalid_values_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "autocompare_config.ini"
            for content, expected in (
                ("", False), ("[database]\n", False),
                ("[database]\nmulti_database_default = invalid\n", False),
                ("[database]\nmulti_database_default = false\n", False),
                ("[database]\nmulti_database_default = true\n", True),
            ):
                with self.subTest(content=content):
                    config_path.write_text(content, encoding="utf-8")
                    self.assertIs(load_app_config(config_path).multi_database_default, expected)

    def test_loads_workflow_specific_excel_headers_with_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "autocompare_config.ini"
            config_path.write_text(
                "\n".join([
                    "[excel_headers]",
                    "left_column_title = BASE_LEFT",
                    "right_column_title = BASE_RIGHT",
                    "left_record_prefix = BASE_BEFORE",
                    "right_record_prefix = BASE_AFTER",
                    "fixme_text = FIXME",
                    "",
                    "[excel_headers_htm_before_after]",
                    "left_column_title = HTM_LEFT",
                    "left_record_prefix = HTM_BEFORE",
                    "",
                    "[excel_headers_htc_before_after]",
                    "right_column_title = HTC_RIGHT",
                    "right_record_prefix = HTC_AFTER",
                    "",
                    "[excel_headers_after_htc_vs_htm]",
                    "left_column_title = AFTER_LEFT",
                    "right_column_title = AFTER_RIGHT",
                    "left_record_prefix = AFTER_BEFORE",
                    "right_record_prefix = AFTER_AFTER",
                    "",
                ]),
                encoding="utf-8",
            )

            config = load_app_config(config_path)

        htm = excel_headers_for_workflow(config, WORKFLOW_HTM_BEFORE_AFTER)
        htc = excel_headers_for_workflow(config, WORKFLOW_HTC_BEFORE_AFTER)
        after = excel_headers_for_workflow(config, WORKFLOW_AFTER_HTC_VS_HTM)

        self.assertEqual(("HTM_LEFT", "BASE_RIGHT", "HTM_BEFORE", "BASE_AFTER"), (
            htm.left_column_title, htm.right_column_title, htm.left_record_prefix, htm.right_record_prefix,
        ))
        self.assertEqual(("BASE_LEFT", "HTC_RIGHT", "BASE_BEFORE", "HTC_AFTER"), (
            htc.left_column_title, htc.right_column_title, htc.left_record_prefix, htc.right_record_prefix,
        ))
        self.assertEqual(("AFTER_LEFT", "AFTER_RIGHT", "AFTER_BEFORE", "AFTER_AFTER"), (
            after.left_column_title, after.right_column_title, after.left_record_prefix, after.right_record_prefix,
        ))


if __name__ == "__main__":
    unittest.main()
