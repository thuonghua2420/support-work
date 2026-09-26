from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import pymupdf
    from reportlab.pdfgen import canvas

    from autocompare_tool.pdf_compare import compare_pdf_files
except ImportError:  # pragma: no cover - dependency guard for broken environments
    pymupdf = None
    canvas = None
    compare_pdf_files = None


@unittest.skipIf(pymupdf is None, "PDF dependencies are not installed")
class PdfCompareTests(unittest.TestCase):
    def test_different_pdfs_create_visual_report_and_machine_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / "old.pdf"
            new_path = root / "new.pdf"
            output_path = root / "compare.pdf"
            _make_pdf(old_path, ["Invoice total: 100", "Second page unchanged"])
            _make_pdf(new_path, ["Invoice total: 125"])

            result = compare_pdf_files(old_path, new_path, output_path)

            self.assertEqual("DIFFERENT", result.verdict)
            self.assertFalse(result.identical)
            self.assertEqual(2, result.compared_page_count)
            self.assertEqual(2, result.different_page_count)
            self.assertGreater(result.difference_region_count, 0)
            self.assertTrue(output_path.is_file())
            self.assertTrue(result.manifest_path.is_file())

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("autocompare.pdf-comparison.v1", manifest["schema"])
            self.assertEqual("DIFFERENT", manifest["summary"]["verdict"])
            self.assertEqual(2, len(manifest["pages"]))
            self.assertFalse(manifest["pages"][0]["text_identical"])
            self.assertFalse(manifest["pages"][1]["new_present"])

            report = pymupdf.open(output_path)
            try:
                report_text = "\n".join(page.get_text() for page in report)
                self.assertGreaterEqual(report.page_count, 2)
                self.assertIn("DIFFERENT", report_text)
                self.assertIn("Page 1 - Differences", report_text)
                self.assertIn("Page 2 - Differences", report_text)
            finally:
                report.close()

    def test_identical_pdf_reports_binary_and_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_path = root / "old.pdf"
            new_path = root / "new.pdf"
            _make_pdf(old_path, ["Exact value: ABC-123"])
            shutil.copyfile(old_path, new_path)

            result = compare_pdf_files(old_path, new_path, root / "result")

            self.assertEqual("BINARY IDENTICAL", result.verdict)
            self.assertTrue(result.identical)
            self.assertTrue(result.binary_identical)
            self.assertTrue(result.text_identical)
            self.assertTrue(result.visual_identical)
            self.assertEqual(0, result.different_page_count)
            self.assertEqual(".pdf", result.output_path.suffix)
            report = pymupdf.open(result.output_path)
            try:
                self.assertEqual(1, report.page_count)
                self.assertIn("BINARY IDENTICAL", report[0].get_text())
            finally:
                report.close()


def _make_pdf(path: Path, page_texts: list[str]) -> None:
    document = canvas.Canvas(str(path))
    for page_number, text in enumerate(page_texts, start=1):
        document.setFont("Helvetica", 12)
        document.drawString(72, 760, text)
        document.drawString(72, 735, f"Page {page_number}")
        document.showPage()
    document.save()


if __name__ == "__main__":
    unittest.main()
