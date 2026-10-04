import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autocompare_tool.text_compare import TextCompareFiles, compare_text_folders, run_folder_compare


class TextCompareTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = TextCompareFiles()

    def save(self, opened, text, **options):
        return self.store.save({"token": opened["token"], "sha256": opened["sha256"], "confirmed": True, "text": text, **options})

    def test_preserve_encodings_bom_and_crlf(self):
        for codec, data in [("utf-8", b"hello\r\n"), ("utf-8-sig", b"\xef\xbb\xbfhello\r\n"), ("utf-16-be", b"\xfe\xff" + "hello\r\n".encode("utf-16-be")), ("utf-32-be", b"\x00\x00\xfe\xff" + "hello\r\n".encode("utf-32-be")), ("cp932", "日本語\r\n".encode("cp932"))]:
            with self.subTest(codec=codec):
                path = self.root / f"{codec}.txt"; path.write_bytes(data)
                opened = self.store.open(str(path))
                self.assertEqual(opened["eol"], "\r\n")
                self.save(opened, "new\n")
                bom = b"\xfe\xff" if codec == "utf-16-be" else b"\x00\x00\xfe\xff" if codec == "utf-32-be" else b""
                self.assertEqual(path.read_bytes(), bom + "new\r\n".encode(codec))

    def test_external_change_is_never_overwritten(self):
        path = self.root / "a.txt"; path.write_bytes(b"before")
        opened = self.store.open(str(path)); path.write_bytes(b"external")
        with self.assertRaises(RuntimeError): self.save(opened, "mine")
        self.assertEqual(path.read_bytes(), b"external")

    def test_confirmation_and_snapshot_required(self):
        path = self.root / "a.txt"; path.write_bytes(b"old")
        opened = self.store.open(str(path))
        with self.assertRaises(PermissionError): self.save(opened, "mine", confirmed=False)
        with self.assertRaises(RuntimeError): self.save(opened, "mine", sha256="wrong")
        self.assertEqual(path.read_bytes(), b"old")

    def test_stale_save_token_after_success_is_rejected(self):
        path = self.root / "a.txt"; path.write_bytes(b"old")
        opened = self.store.open(str(path)); self.save(opened, "new")
        with self.assertRaises(RuntimeError): self.save(opened, "stale")
        self.assertEqual(path.read_bytes(), b"new")

    def test_mixed_eol_requires_explicit_conversion(self):
        path = self.root / "a.txt"; path.write_bytes(b"a\r\nb\nc\r")
        opened = self.store.open(str(path))
        self.assertEqual(opened["eol"], "mixed")
        with self.assertRaises(ValueError): self.save(opened, "a\nb\nc\n")
        self.save(opened, "a\nb\nc\n", eol="\n")
        self.assertEqual(path.read_bytes(), b"a\nb\nc\n")

    def test_binary_large_and_too_many_lines_rejected(self):
        for data in [b"a\x00b", b"a" * 1_000_001, b"x\n" * 10001]:
            path = self.root / "a.txt"; path.write_bytes(data)
            with self.assertRaises(ValueError): self.store.open(str(path))

    def test_no_final_newline_preserved(self):
        path = self.root / "a.txt"; path.write_bytes(b"a\r\nb")
        opened = self.store.open(str(path)); self.save(opened, "a\nb")
        self.assertEqual(path.read_bytes(), b"a\r\nb")

    def test_unrepresentable_cp932_character_does_not_damage_original(self):
        path = self.root / "jp.txt"; original = "日本語".encode("cp932"); path.write_bytes(original)
        opened = self.store.open(str(path))
        with self.assertRaises(ValueError): self.save(opened, "😀")
        self.assertEqual(path.read_bytes(), original)

    def test_readonly_file_is_not_replaced(self):
        import os
        import stat
        path = self.root / "readonly.txt"; path.write_bytes(b"old")
        opened = self.store.open(str(path)); os.chmod(path, stat.S_IREAD)
        try:
            with self.assertRaises(PermissionError): self.save(opened, "new")
            self.assertEqual(path.read_bytes(), b"old")
        finally: os.chmod(path, stat.S_IREAD | stat.S_IWRITE)

    def test_entry_limit_is_reported_not_silently_truncated(self):
        left, right = self.fixtures()
        for name in ["a", "b"]: (left / name).write_bytes(b"x")
        with patch("autocompare_tool.text_compare.MAX_ENTRIES", 1):
            with self.assertRaisesRegex(ValueError, "20.000"): compare_text_folders(left, right)

    def test_failed_replace_leaves_original_and_cleans_temp(self):
        path = self.root / "a.txt"; path.write_bytes(b"original")
        opened = self.store.open(str(path))
        with patch("autocompare_tool.text_compare.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError): self.save(opened, "new")
        self.assertEqual(path.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob(".compare-*")), [])

    def fixtures(self):
        left, right = self.root / "left", self.root / "right"
        left.mkdir(); right.mkdir()
        return left, right

    def test_folder_classification_exact_bytes_and_empty_directories(self):
        left, right = self.fixtures()
        for folder in [left, right]:
            (folder / "empty").mkdir(); (folder / "same.bin").write_bytes(b"\x00\x01\xff")
        (left / "eol.txt").write_bytes(b"x\r\n"); (right / "eol.txt").write_bytes(b"x\n")
        (left / "same-size.txt").write_bytes(b"abc"); (right / "same-size.txt").write_bytes(b"abd")
        (left / "a.txt").write_bytes(b"a"); (right / "b.txt").write_bytes(b"b")
        (left / "conflict").mkdir(); (right / "conflict").write_bytes(b"c")
        results = compare_text_folders(str(left), str(right))
        statuses = {row["path"]: row["status"] for row in results["rows"]}
        self.assertEqual(statuses, {"same.bin": "same", "empty": "folder", "eol.txt": "different", "same-size.txt": "different", "a.txt": "left-only", "b.txt": "right-only", "conflict": "type-conflict"})

    def test_regex_filters_exclude_subtrees_and_include_files(self):
        left, right = self.fixtures()
        for folder in [left, right]:
            (folder / ".git").mkdir(); (folder / ".git" / "config").write_bytes(b"x")
            for name in ["a.py", "b.txt", "ignored.log"]: (folder / name).write_bytes(b"x")
        result = compare_text_folders(left, right, include=r"\.py$")
        self.assertEqual([row["path"] for row in result["rows"]], ["a.py"])
        with self.assertRaisesRegex(ValueError, "Regex"): compare_text_folders(left, right, include="[")

    def test_symlink_is_not_followed(self):
        left, right = self.fixtures()
        path = left / "link"
        try: path.symlink_to(self.root, target_is_directory=True)
        except OSError: self.skipTest("Symlink privilege unavailable")
        result = compare_text_folders(left, right)
        self.assertEqual(result["rows"][0]["status"], "skipped")

    def test_file_changed_during_scan_is_reported(self):
        left, right = self.fixtures()
        for folder in (left, right): (folder / "a.txt").write_bytes(b"same")
        def activity(message):
            if message.startswith("Đọc nội dung"): (left / "a.txt").write_bytes(b"changed")
        result = compare_text_folders(left, right, activity=activity)
        self.assertEqual(result["rows"][0]["status"], "error")

    def test_unreadable_directory_never_means_files_are_missing(self):
        import os
        left, right = self.fixtures()
        for root in [left, right]:
            (root / "private").mkdir(); (root / "private" / "exists.txt").write_bytes(b"same")
        scan = os.scandir
        def guarded_scan(path):
            if Path(path).resolve() == (left / "private").resolve(): raise PermissionError("denied")
            return scan(path)
        with patch("autocompare_tool.text_compare.os.scandir", side_effect=guarded_scan):
            result = compare_text_folders(left, right)
        self.assertEqual({row["path"]: row["status"] for row in result["rows"]},
                         {"private": "error", "private/exists.txt": "error"})

    def test_real_spawned_scan_returns_results(self):
        left, right = self.fixtures(); (left / "new.txt").write_bytes(b"new")
        result = run_folder_compare(str(left), str(right))
        self.assertEqual(result["counts"], {"left-only": 1})


if __name__ == "__main__": unittest.main()
