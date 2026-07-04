"""classify：三態分類與格式挑選。"""

import unittest

from openshelf.classify import classify, pick_acsm_option, pick_book_option
from openshelf.playbooks import ExportOption


class Classify(unittest.TestCase):
    def test_drm_free(self):
        self.assertEqual(
            classify([ExportOption("epub", "u"), ExportOption("pdf", "u")]), "drm_free"
        )

    def test_acsm(self):
        self.assertEqual(classify([ExportOption("acsm", "u")]), "acsm")

    def test_no_export(self):
        self.assertEqual(classify([]), "no_export")

    def test_drm_free_wins_over_acsm(self):
        # 同時有書檔與 acsm 時，視為可直接下載
        self.assertEqual(
            classify([ExportOption("epub", "u"), ExportOption("acsm", "u")]), "drm_free"
        )


class PickOptions(unittest.TestCase):
    def setUp(self):
        self.opts = [ExportOption("pdf", "PDF"), ExportOption("epub", "EPUB")]

    def test_prefer_epub(self):
        self.assertEqual(pick_book_option(self.opts, "epub").url, "EPUB")

    def test_prefer_pdf(self):
        self.assertEqual(pick_book_option(self.opts, "pdf").url, "PDF")

    def test_fallback_when_preferred_missing(self):
        only_pdf = [ExportOption("pdf", "PDF")]
        self.assertEqual(pick_book_option(only_pdf, "epub").url, "PDF")

    def test_pick_acsm(self):
        opts = [ExportOption("acsm", "ACSM")]
        self.assertEqual(pick_acsm_option(opts).url, "ACSM")
        self.assertIsNone(pick_acsm_option([ExportOption("epub", "u")]))


if __name__ == "__main__":
    unittest.main()
