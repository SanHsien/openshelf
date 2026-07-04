"""manifest：讀寫、統計、續傳判斷。"""

import tempfile
import unittest
from pathlib import Path

from openshelf.manifest import BookEntry, Manifest


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "manifest.json"

    def test_roundtrip(self):
        m = Manifest(self.path)
        m.upsert(BookEntry(volume_id="A", title="書", author="作", category="acsm"))
        m.save()
        loaded = Manifest.load(self.path)
        self.assertIn("A", loaded.books)
        self.assertEqual(loaded.books["A"].category, "acsm")
        self.assertFalse((self.dir / "manifest.json.tmp").exists())

    def test_counts(self):
        m = Manifest(self.path)
        m.upsert(BookEntry(volume_id="A", category="drm_free"))
        m.upsert(BookEntry(volume_id="B", category="acsm"))
        m.upsert(BookEntry(volume_id="C", category="acsm"))
        c = m.counts()
        self.assertEqual(c["total"], 3)
        self.assertEqual(c["acsm"], 2)
        self.assertEqual(c["drm_free"], 1)

    def test_is_downloaded(self):
        m = Manifest(self.path)
        (self.dir / "book.epub").write_bytes(b"x")
        m.upsert(
            BookEntry(volume_id="A", category="drm_free", file_path="book.epub")
        )
        m.upsert(BookEntry(volume_id="B", category="acsm", file_path="missing.acsm"))
        m.upsert(BookEntry(volume_id="C", category="no_export"))
        self.assertTrue(m.is_downloaded("A", self.dir))
        self.assertFalse(m.is_downloaded("B", self.dir))  # 檔案不存在
        self.assertFalse(m.is_downloaded("C", self.dir))  # 無檔案

    def test_load_missing_file(self):
        m = Manifest.load(self.dir / "nope.json")
        self.assertEqual(m.books, {})


if __name__ == "__main__":
    unittest.main()
