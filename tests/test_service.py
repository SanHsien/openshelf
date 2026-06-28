"""service：同名書辨識與 .acsm 時效（以下載時間為準）。"""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openshelf.config import Config
from openshelf.manifest import BookEntry, Manifest
from openshelf.playbooks import ExportOption
from openshelf.service import (
    CSV_NAME,
    HTML_NAME,
    REPORT_NAME,
    _candidates,
    _disambiguator,
    _is_stale_acsm,
    _should_refresh_acsm,
    count_stale_acsm,
    write_csv,
    write_html,
    write_report,
)


def _cfg(acsm_valid_days=7):
    p = Path(".")
    return Config(
        base_dir=p, output_dir=p, profile_dir=p, storage_state=p,
        prefer_format="epub", include_acsm=True, throttle_seconds=0,
        download_timeout=1, download_retries=1, acsm_valid_days=acsm_valid_days,
        calibredb_path=None, calibre_library=None, ade_path=None,
    )


def _book(vid, title="塑膠鴉片", author="夏傳位", publisher="", published=""):
    return BookEntry(
        volume_id=vid, title=title, author=author,
        publisher=publisher, published=published,
    )


class Disambiguator(unittest.TestCase):
    def test_single_no_suffix(self):
        b = _book("A")
        self.assertIsNone(_disambiguator(b, [b]))

    def test_distinguish_by_year(self):
        a = _book("A", publisher="WANDERER", published="2008-03-18")
        b = _book("B", publisher="Puomo", published="2013-09-29")
        group = [a, b]
        self.assertEqual(_disambiguator(a, group), "2008 · WANDERER")
        self.assertEqual(_disambiguator(b, group), "2013 · Puomo")

    def test_same_year_publisher_falls_back_to_volume_id(self):
        a = _book("AAA", title="藝術欣賞", publisher="Puomo", published="2013-10-06")
        b = _book("BBB", title="藝術欣賞", publisher="Puomo", published="2013-10-06")
        group = [a, b]
        self.assertIn("AAA", _disambiguator(a, group))
        self.assertIn("BBB", _disambiguator(b, group))
        self.assertNotEqual(_disambiguator(a, group), _disambiguator(b, group))


class Candidates(unittest.TestCase):
    def test_drm_free_orders_by_preference(self):
        opts = [ExportOption("pdf", "P"), ExportOption("epub", "E")]
        self.assertEqual([c.url for c in _candidates("drm_free", opts, "epub")], ["E", "P"])
        self.assertEqual([c.url for c in _candidates("drm_free", opts, "pdf")], ["P", "E"])

    def test_drm_free_single_format(self):
        opts = [ExportOption("epub", "E")]
        self.assertEqual([c.url for c in _candidates("drm_free", opts, "epub")], ["E"])

    def test_acsm(self):
        opts = [ExportOption("acsm", "A1"), ExportOption("acsm", "A2")]
        self.assertEqual([c.url for c in _candidates("acsm", opts, "epub")], ["A1", "A2"])

    def test_no_export(self):
        self.assertEqual(_candidates("no_export", [], "epub"), [])


class AcsmStaleness(unittest.TestCase):
    def _entry(self, days_ago, category="acsm", file_path="x.acsm"):
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        e = _book("A")
        e.category = category
        e.file_path = file_path
        e.downloaded_at = dt.isoformat(timespec="seconds")
        return e

    def test_fresh_not_stale(self):
        self.assertFalse(_is_stale_acsm(self._entry(1), _cfg(7)))

    def test_old_is_stale(self):
        self.assertTrue(_is_stale_acsm(self._entry(10), _cfg(7)))

    def test_drm_free_never_stale(self):
        self.assertFalse(_is_stale_acsm(self._entry(100, category="drm_free"), _cfg(7)))

    def test_no_timestamp_not_stale(self):
        e = _book("A")
        e.category = "acsm"
        e.file_path = "x.acsm"
        self.assertFalse(_is_stale_acsm(e, _cfg(7)))

    def test_count(self):
        m = Manifest(Path("dummy"))
        m.books["A"] = self._entry(10)
        m.books["B"] = self._entry(1)
        m.books["C"] = self._entry(30)
        self.assertEqual(count_stale_acsm(m, _cfg(7)), 2)

    def test_force_refresh_acsm_ignores_valid_days(self):
        fresh = self._entry(1)
        self.assertFalse(_should_refresh_acsm(fresh, _cfg(7), False, False))
        self.assertTrue(_should_refresh_acsm(fresh, _cfg(7), False, True))

    def test_refresh_acsm_only_refreshes_stale(self):
        fresh = self._entry(1)
        old = self._entry(10)
        self.assertFalse(_should_refresh_acsm(fresh, _cfg(7), True, False))
        self.assertTrue(_should_refresh_acsm(old, _cfg(7), True, False))


class Report(unittest.TestCase):
    def test_report_lists_missing(self):
        import tempfile

        out = Path(tempfile.mkdtemp())
        cfg = Config(
            base_dir=out, output_dir=out, profile_dir=out, storage_state=out,
            prefer_format="epub", include_acsm=True, throttle_seconds=0,
            download_timeout=1, download_retries=1, acsm_valid_days=7,
            calibredb_path=None, calibre_library=None, ade_path=None,
        )
        m = Manifest(out / "manifest.json")
        f = _book("F", title="Remix", author="Lessig")
        f.category = "failed"
        f.note = "HTTPStatusError: 404"
        ne = _book("N", title="某雜誌", author="出版社")
        ne.category = "no_export"
        ok = _book("D", title="可下載書")
        ok.category = "drm_free"
        ok.file_path = "可下載書.epub"
        for b in (f, ne, ok):
            m.books[b.volume_id] = b

        path = write_report(m, cfg)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, REPORT_NAME)
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("Remix", text)
        self.assertIn("404", text)        # 失敗原因有寫入
        self.assertIn("某雜誌", text)      # 無法匯出有列出
        self.assertIn("失敗（未取得書檔）：1", text)


class CsvHtmlExport(unittest.TestCase):
    def _manifest_cfg(self):
        import tempfile

        out = Path(tempfile.mkdtemp())
        cfg = Config(
            base_dir=out, output_dir=out, profile_dir=out, storage_state=out,
            prefer_format="epub", include_acsm=True, throttle_seconds=0,
            download_timeout=1, download_retries=1, acsm_valid_days=7,
            calibredb_path=None, calibre_library=None, ade_path=None,
        )
        m = Manifest(out / "manifest.json")
        a = _book("A", title="無DRM書", author="作者甲", publisher="左岸", published="2019")
        a.category = "drm_free"; a.file_path = "無DRM書.epub"
        f = _book("F", title="壞,書", author='含"逗號')  # 測 CSV 跳脫
        f.category = "failed"; f.note = "404"
        for b in (a, f):
            m.books[b.volume_id] = b
        return m, cfg

    def test_csv(self):
        import csv

        m, cfg = self._manifest_cfg()
        path = write_csv(m, cfg)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, CSV_NAME)
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][0], "書名")
        titles = {r[0] for r in rows[1:]}
        self.assertIn("無DRM書", titles)
        self.assertIn("壞,書", titles)  # 逗號正確跳脫成單一欄位

    def test_html(self):
        m, cfg = self._manifest_cfg()
        path = write_html(m, cfg)
        self.assertTrue(path.exists())
        self.assertEqual(path.name, HTML_NAME)
        text = path.read_text(encoding="utf-8")
        self.assertIn("<table", text)
        self.assertIn("無DRM書", text)
        self.assertIn("&quot;", text)  # 雙引號有 HTML escape
        self.assertIn('class="failed"', text)


if __name__ == "__main__":
    unittest.main()
