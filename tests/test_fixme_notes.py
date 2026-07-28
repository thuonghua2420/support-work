from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autocompare_tool.fixme_notes import FixmeNoteStore


class FixmeNoteStoreTests(unittest.TestCase):
    def test_upsert_replace_and_delete_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FixmeNoteStore(Path(temp_dir) / "notes.json")

            notes = store.upsert("KNOWN_DIFF", "Expected difference")
            self.assertEqual([(note.value, note.meaning) for note in notes], [("KNOWN_DIFF", "Expected difference")])

            notes = store.replace("KNOWN_DIFF", "SPEC_CHANGE", "Changed by specification")
            self.assertEqual([(note.value, note.meaning) for note in notes], [("SPEC_CHANGE", "Changed by specification")])

            notes = store.delete("SPEC_CHANGE")
            self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
