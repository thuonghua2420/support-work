from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "run.bat is Windows-only")
class RunBatTests(unittest.TestCase):
    def test_missing_compatible_python_fails_with_actionable_message(self) -> None:
        source = Path(__file__).resolve().parents[1] / "run.bat"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(source, root / "run.bat")
            binaries = root / "bin"
            binaries.mkdir()
            for command in ("py", "python"):
                (binaries / f"{command}.cmd").write_text("@echo off\r\nexit /b 1\r\n", encoding="ascii")
            environment = os.environ.copy()
            environment["PATH"] = os.pathsep.join((str(binaries), str(Path(os.environ["SystemRoot"]) / "System32")))

            result = self._run(root, environment)

            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertIn("Python 3.10 through 3.14", result.stdout)
            self.assertFalse((root / ".runtime-venv").exists())

    def test_fresh_copy_creates_compatible_venv_and_reuses_it(self) -> None:
        if not (sys.version_info.major == 3 and sys.version_info.minor in range(10, 15)):
            self.skipTest("requires a supported Python to run the isolated launcher smoke test")

        source = Path(__file__).resolve().parents[1] / "run.bat"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copy2(source, root / "run.bat")
            (root / "requirements.txt").write_text("\n", encoding="utf-8")
            package = root / "autocompare_tool"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "__main__.py").write_text("print('Launcher smoke OK')\n", encoding="utf-8")
            pil = root / "PIL"
            pil.mkdir()
            (pil / "__init__.py").write_text("", encoding="utf-8")
            (pil / "Image.py").write_text("", encoding="utf-8")
            for module in ("pymupdf", "reportlab", "pyodbc", "oracledb"):
                (root / f"{module}.py").write_text("", encoding="utf-8")

            binaries = root / "bin"
            binaries.mkdir()
            (binaries / "py.cmd").write_text("@echo off\r\nexit /b 1\r\n", encoding="ascii")
            (binaries / "python.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" %*\r\n', encoding="utf-8"
            )
            environment = os.environ.copy()
            environment["PATH"] = str(binaries) + os.pathsep + environment.get("PATH", "")
            environment["PYTHONDONTWRITEBYTECODE"] = "1"

            first = self._run(root, environment)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertIn("Creating virtual environment", first.stdout)
            self.assertIn("Launcher smoke OK", first.stdout)

            second = self._run(root, environment)
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertNotIn("Rebuilding incompatible", second.stdout)
            self.assertIn("Launcher smoke OK", second.stdout)

    @staticmethod
    def _run(root: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", str(root / "run.bat"), "8877"],
            cwd=root,
            env=environment,
            input="\n",
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
