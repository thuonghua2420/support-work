"""Run dependency-free browser logic regressions in the default unittest gate."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is not installed")
class WebCompareNoteSmokeTests(unittest.TestCase):
    def test_filtered_note_rounds(self) -> None:
        self._run_smoke("web_compare_note_rounds.cjs")

    def test_selection_across_sheets(self) -> None:
        self._run_smoke("web_compare_multi_sheet_notes.cjs")

    def _run_smoke(self, filename: str) -> None:
        result = subprocess.run(
            [NODE, str(ROOT / "tests" / filename)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
