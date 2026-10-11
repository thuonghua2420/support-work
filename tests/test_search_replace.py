import codecs
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from autocompare_tool.search_replace import (
    SearchReplace, compile_globs, compile_query, decode_file, patch_bytes,
    replacement_text, scan,
)


class SearchReplaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.service = SearchReplace()

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def search(self, query="foo", **options):
        token = self.service.start({"root": str(self.root), "query": query, **options})
        files, cursor = [], 0
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.service.poll({**token, "cursor": cursor})
            files.extend(result["files"])
            cursor = result["cursor"]
            if result["done"] and not result["has_more"]:
                self.assertFalse(result["error"], result)
                return {**token, "files": files, "status": result}
            time.sleep(.02)
        self.fail("Search worker timed out")

    def apply(self, result, replacement="bar", **scope):
        plan = self.service.prepare({"id": result["id"], "replacement": replacement, **scope})
        return self.service.apply({"token": plan["token"], "confirmed": True})

    def test_mixed_encodings_boms_eols_replace_and_undo_exact_bytes(self):
        originals = {}
        for name, encoding, bom in [("utf8", "utf-8", b""), ("utf8bom", "utf-8", codecs.BOM_UTF8),
                                    ("sjis", "shift_jis", b""), ("cp932", "cp932", b""),
                                    ("utf16", "utf-16-le", codecs.BOM_UTF16_LE),
                                    ("utf32", "utf-32-be", codecs.BOM_UTF32_BE)]:
            text = "日本語 foo\r\nfoo\nfoo\rend"
            original = bom + text.encode(encoding)
            path = self.write(name + ".txt", original)
            originals[path] = original
        found = self.search()
        self.assertEqual(found["status"]["count"], 18)
        result = self.apply(found, "bar")
        self.assertEqual(len(result["written"]), 6)
        for file in found["files"]:
            path = self.root / file["path"]
            before, codec, bom = decode_file(originals[path])
            self.assertEqual(path.read_bytes(), bom + before.replace("foo", "bar").encode(codec))
        self.service.undo({"confirmed": True})
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)

    def test_cp932_duplicate_mapping_untouched_bytes_preserved(self):
        # CP932 Roman numeral I: 0xFA4A decodes to the same char as 0x8754.
        data = b"\xfa\x4a foo\r\n\xfa\x4a foo"
        text, codec, bom = decode_file(data)
        self.assertNotEqual(text.encode(codec), data)
        matches = list(compile_query({"query": "foo"}).finditer(text))
        result = patch_bytes(data, text, codec, bom, [(m.start(), m.end(), "日本") for m in matches])
        self.assertEqual(result, data.replace(b"foo", "日本".encode("cp932")))
        self.assertEqual(patch_bytes(data, text, codec, bom, [(0, 1, text[0])]), data)

    def test_encoding_alias_cannot_silently_change_replacement(self):
        # Shift JIS can encode YEN SIGN as a backslash, despite strict encoding.
        with self.assertRaises(UnicodeError):
            patch_bytes(b"foo", "foo", "shift_jis", b"", [(0, 3, "\u00a5")])

    def test_unencodable_replacement_prevents_entire_batch(self):
        one = self.write("1.txt", b"foo")
        two = self.write("2.txt", "日本 foo".encode("cp932"))
        found = self.search()
        with self.assertRaises(ValueError):
            self.service.prepare({"id": found["id"], "replacement": "😀"})
        self.assertEqual(one.read_bytes(), b"foo")
        self.assertEqual(two.read_bytes(), "日本 foo".encode("cp932"))

    def test_preflight_conflict_and_confirmation(self):
        a = self.write("a.txt", b"foo")
        b = self.write("b.txt", b"foo")
        found = self.search()
        plan = self.service.prepare({"id": found["id"], "replacement": "bar"})
        with self.assertRaises(PermissionError):
            self.service.apply({"token": plan["token"]})
        b.write_bytes(b"external")
        with self.assertRaises(ValueError):
            self.service.apply({"token": plan["token"], "confirmed": True})
        self.assertEqual(a.read_bytes(), b"foo")
        self.assertEqual(b.read_bytes(), b"external")

    def test_single_match_file_all_and_dismiss(self):
        a = self.write("a.txt", b"foo foo")
        b = self.write("b.txt", b"foo foo")
        found = self.search()
        self.apply(found, "one", file_id=0, match_id=1)
        self.assertEqual(a.read_bytes(), b"foo one")
        self.assertEqual(b.read_bytes(), b"foo foo")
        found = self.search()
        self.service.dismiss({"id": found["id"], "file_id": 1, "match_id": 0})
        self.apply(found, "two", file_id=1)
        self.assertEqual(b.read_bytes(), b"foo two")
        found = self.search()
        self.service.dismiss({"id": found["id"], "file_id": 0})
        self.apply(found, "three")
        self.assertEqual(a.read_bytes(), b"foo one")
        self.assertEqual(b.read_bytes(), b"three two")

    def test_query_options_and_regex_captures_preserve_case(self):
        file = self.write("test.txt", b"foo FOO Foo food\r\nfoo_12\nbar_34")
        found = self.search(whole_word=True, match_case=True)
        self.assertEqual(found["status"]["count"], 1)
        found = self.search(whole_word=True)
        self.apply(found, "word", preserve_case=True)
        self.assertEqual(file.read_bytes(), b"word WORD Word food\r\nfoo_12\nbar_34")
        found = self.search(r"(?<name>foo|bar)_(\d+)", regex=True)
        self.apply(found, r"\U$<name>\E:$2:$$:\n")
        self.assertEqual(file.read_bytes(), b"word WORD Word food\r\nFOO:12:$:\n\nBAR:34:$:\n")

    def test_multiline_zero_width_empty_replacement_and_literal_dollars(self):
        file = self.write("test.txt", b"foo\r\nfoo\nend")
        found = self.search("foo\r\nfoo")
        self.apply(found, "$1\\n")
        self.assertEqual(file.read_bytes(), b"$1\\n\nend")
        found = self.search("^", regex=True)
        self.apply(found, ">")
        self.assertEqual(file.read_bytes(), b">$1\\n\n>end")
        found = self.search(">")
        self.apply(found, "")
        self.assertEqual(file.read_bytes(), b"$1\\n\nend")

    def test_globs_nested_braces_anchor_and_exclude(self):
        for name in ["a.sql", "sub/b.cs", "sub/c.txt", "out/d.sql", "sub/out/e.sql"]:
            self.write(name, b"foo")
        found = self.search(include="**/*.{sql,cs}", exclude="out")
        self.assertEqual([f["path"] for f in found["files"]], ["a.sql", "sub/b.cs"])
        found = self.search(include="./*.sql")
        self.assertEqual([f["path"] for f in found["files"]], ["a.sql"])
        self.assertTrue(any(p.fullmatch("sub/a1.sql") for p in compile_globs("**/a[0-9].???")))

    def test_preview_matches_written_bytes_and_no_write_on_preview(self):
        original = codecs.BOM_UTF16_BE + "foo\r\n日本".encode("utf-16-be")
        path = self.write("a.txt", original)
        found = self.search()
        view = self.service.preview({"id": found["id"], "file_id": 0, "replacement": "bar"})
        self.assertEqual(view["text"], "foo\r\n日本")
        self.assertEqual(view["after"], "bar\r\n日本")
        self.assertEqual(path.read_bytes(), original)
        self.apply(found)
        self.assertEqual(decode_file(path.read_bytes())[0], view["after"])

    def test_unknown_encoding_binary_and_limits_reported(self):
        self.write("binary", b"foo\x00bar")
        self.write("broken", b"\x81")
        self.write("valid", b"foo")
        found = self.search()
        self.assertEqual(found["status"]["skipped"], 2)
        self.assertEqual(len(found["files"]), 1)
        events = []
        with patch("autocompare_tool.search_replace.MAX_MATCHES", 0):
            scan({"root": str(self.root), "query": "foo"}, events.append)
        self.assertTrue(events[-1]["limited"])

    def test_invalid_regex_stale_session_and_cancel(self):
        self.write("a", b"foo")
        with self.assertRaises(ValueError):
            self.service.start({"root": str(self.root), "query": "[", "regex": True})
        first = self.search()
        second = self.search()
        with self.assertRaises(ValueError):
            self.service.prepare({"id": first["id"], "replacement": "bar"})
        self.service.cancel(second)
        with self.assertRaises(ValueError):
            self.service.prepare({"id": second["id"], "replacement": "bar"})

    def test_partial_io_failure_reported_and_undo_only_written_files(self):
        from autocompare_tool.search_replace import atomic_write
        a = self.write("a", b"foo")
        b = self.write("b", b"foo")
        found = self.search()
        def fail_second(path, data):
            if path == b:
                raise PermissionError("locked")
            atomic_write(path, data)
        with patch("autocompare_tool.search_replace.atomic_write", side_effect=fail_second):
            result = self.apply(found)
        self.assertEqual(result["written"], [str(a)])
        self.assertEqual(result["error"], "locked")
        self.service.undo({"confirmed": True})
        self.assertEqual(a.read_bytes(), b"foo")
        self.assertEqual(b.read_bytes(), b"foo")

    def test_undo_refuses_external_change(self):
        path = self.write("a", b"foo")
        found = self.search()
        self.apply(found)
        path.write_bytes(b"external")
        with self.assertRaises(ValueError):
            self.service.undo({"confirmed": True})
        self.assertEqual(path.read_bytes(), b"external")

    def test_catastrophic_regex_can_be_cancelled(self):
        self.write("slow.txt", b"a" * 5000 + b"!")
        token = self.service.start({"root": str(self.root), "query": "(a+)+$", "regex": True})
        time.sleep(.15)
        started = time.monotonic()
        self.service.cancel(token)
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(self.service.poll(token)["done"])

    def test_replacement_output_limit_before_writing(self):
        path = self.write("a", b"foo foo")
        found = self.search()
        with patch("autocompare_tool.search_replace.MAX_FILE_BYTES", 8):
            with self.assertRaises(ValueError):
                self.service.prepare({"id": found["id"], "replacement": "long-replacement"})
        self.assertEqual(path.read_bytes(), b"foo foo")


if __name__ == "__main__":
    unittest.main()
