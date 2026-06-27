"""export：檔名與覆核。"""

import tempfile
import unittest
from pathlib import Path

from openshelf.export import BOOK_MIN_BYTES, VerifyError, _verify, safe_filename


class SafeFilename(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(safe_filename("書名", "作者", "epub"), "書名 - 作者.epub")

    def test_no_author(self):
        self.assertEqual(safe_filename("書名", "", "pdf"), "書名.pdf")

    def test_illegal_chars(self):
        name = safe_filename('a/b:c*d?"<>|', "x", "epub")
        for ch in '/\\:*?"<>|':
            self.assertNotIn(ch, name)

    def test_disambiguator(self):
        name = safe_filename("書名", "作者", "acsm", disambiguator="VOL123")
        self.assertEqual(name, "書名 - 作者 [VOL123].acsm")

    def test_disambiguator_sanitized(self):
        # 出版社字串可能含非法字元（引號/斜線），須清掉
        name = safe_filename("書名", "作者", "epub", disambiguator='2013 · "O/Reilly"')
        for ch in '/\\:*?"<>|':
            self.assertNotIn(ch, name)
        self.assertIn("2013", name)

    def test_truncation(self):
        name = safe_filename("書" * 500, "作者", "epub")
        self.assertLessEqual(len(name), 200)

    def test_long_name_preserves_disambiguator(self):
        a = safe_filename("書" * 500, "作者", "epub", disambiguator="VOL_A")
        b = safe_filename("書" * 500, "作者", "epub", disambiguator="VOL_B")
        self.assertNotEqual(a, b)
        self.assertIn("VOL_A", a)
        self.assertIn("VOL_B", b)
        self.assertLessEqual(len(a), 200)
        self.assertLessEqual(len(b), 200)

    def test_empty_title(self):
        self.assertEqual(safe_filename("", "", "pdf"), "untitled.pdf")


class Verify(unittest.TestCase):
    def _write(self, data: bytes) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "f"
        tmp.write_bytes(data)
        return tmp

    def test_epub_ok(self):
        _verify(self._write(b"PK\x03\x04" + b"0" * BOOK_MIN_BYTES), "epub")

    def test_epub_bad_magic(self):
        with self.assertRaises(VerifyError):
            _verify(self._write(b"<html>" + b"0" * BOOK_MIN_BYTES), "epub")

    def test_pdf_ok(self):
        _verify(self._write(b"%PDF-1.7" + b"0" * BOOK_MIN_BYTES), "pdf")

    def test_book_too_small(self):
        with self.assertRaises(VerifyError):
            _verify(self._write(b"PK\x03\x04small"), "epub")

    def test_acsm_ok(self):
        _verify(self._write(b"<fulfillmentToken/>"), "acsm")

    def test_acsm_too_large(self):
        with self.assertRaises(VerifyError):
            _verify(self._write(b"0" * (128 * 1024)), "acsm")

    def test_empty(self):
        with self.assertRaises(VerifyError):
            _verify(self._write(b""), "acsm")


if __name__ == "__main__":
    unittest.main()
