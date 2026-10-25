"""scan / export 主流程整合測試：以 MockTransport 取代 Google，不連網、不需登入態。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from openshelf import service
from openshelf.config import Config
from openshelf.manifest import Manifest
from openshelf.playbooks import ExportOption, IncompleteLibrary
from openshelf.session import SessionExpired

EPUB = b"PK\x03\x04" + b"0" * 20000
PDF = b"%PDF-" + b"0" * 20000


def _cfg(out: Path) -> Config:
    return Config(
        base_dir=out, output_dir=out, profile_dir=out, storage_state=out,
        prefer_format="epub", include_acsm=True, throttle_seconds=0,
        download_timeout=1, download_retries=1, acsm_valid_days=7,
        calibredb_path=None, calibre_library=None, ade_path=None,
    )


def _lib_book(vid, title, url_fmt=("epub", "https://x/{vid}.epub")):
    from tests.test_integration import _book

    fmt, url = url_fmt
    code = 1 if fmt == "epub" else 2
    block = [3, None, 2, None, [None, 0], None, 1, None, None,
             [[[code, url.format(vid=vid)]]]]
    return _book(vid, title, block)


class _Env(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._close_log)
        self.out = Path(self._tmp.name)
        self.cfg = _cfg(self.out)

    @staticmethod
    def _close_log():
        import logging

        logger = logging.getLogger("openshelf")
        for h in list(logger.handlers):
            logger.removeHandler(h)
            h.close()
        logger._openshelf_path = None

    def _patch_client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        client.cookies.set("SAPISID", "DUMMY", domain="google.com")
        p = mock.patch.object(service, "build_client", lambda cfg: client)
        p.start()
        self.addCleanup(p.stop)


class ScanFlow(_Env):
    def test_scan_adds_books_and_keeps_downloaded_file(self):
        lib = [[_lib_book("A", "書A"), _lib_book("B", "書B")], [2], None]
        self._patch_client(lambda req: httpx.Response(200, json=lib))
        m = Manifest(self.out / "manifest.json")
        from openshelf.manifest import BookEntry

        m.upsert(BookEntry(volume_id="A", title="舊名", category="drm_free", file_path="a.epub"))
        m.save()

        res = service.scan(self.cfg, log=lambda s: None)

        self.assertEqual(res.manifest.get("A").title, "書A")
        self.assertEqual(res.manifest.get("A").file_path, "a.epub")  # 保留既有下載
        self.assertEqual(res.manifest.get("B").category, "drm_free")

    def test_incomplete_library_does_not_write_manifest(self):
        lib = [[_lib_book("A", "書A")], [99], None]
        self._patch_client(lambda req: httpx.Response(200, json=lib))
        with self.assertRaises(IncompleteLibrary):
            service.scan(self.cfg, log=lambda s: None)
        self.assertFalse((self.out / "manifest.json").exists())


class InactiveSync(_Env):
    def _seed(self, ids):
        from openshelf.manifest import BookEntry

        m = Manifest(self.out / "manifest.json")
        for vid in ids:
            m.upsert(BookEntry(volume_id=vid, title=f"書{vid}", category="drm_free",
                               file_path=f"{vid}.epub"))
        m.save()
        for vid in ids:
            (self.out / f"{vid}.epub").write_bytes(EPUB)

    def _scan(self, ids):
        lib = [[_lib_book(v, f"書{v}") for v in ids], [len(ids)], None]
        self._patch_client(lambda req: httpx.Response(200, json=lib))
        return service.scan(self.cfg, log=lambda s: None)

    def test_removed_book_marked_inactive_but_kept(self):
        self._seed(["A", "B"])
        res = self._scan(["A"])
        b = res.manifest.get("B")
        self.assertFalse(b.in_library)
        self.assertEqual(b.file_path, "B.epub")  # 資料保留
        self.assertTrue((self.out / "B.epub").exists())  # 檔案保留
        self.assertTrue(res.manifest.get("A").in_library)
        self.assertEqual(res.manifest.counts()["inactive"], 1)
        self.assertEqual(res.manifest.counts()["total"], 2)

    def test_book_returning_to_library_is_active_again(self):
        self._seed(["A", "B"])
        self._scan(["A"])
        res = self._scan(["A", "B"])
        self.assertTrue(res.manifest.get("B").in_library)
        self.assertTrue(res.manifest.get("B").last_seen_at)

    def test_incomplete_scan_does_not_mark_inactive(self):
        self._seed(["A", "B"])
        lib = [[_lib_book("A", "書A")], [99], None]
        self._patch_client(lambda req: httpx.Response(200, json=lib))
        with self.assertRaises(IncompleteLibrary):
            service.scan(self.cfg, log=lambda s: None)
        m = Manifest.load(self.out / "manifest.json")
        self.assertTrue(all(b.in_library for b in m.books.values()))

    def test_response_without_total_does_not_mark_inactive(self):
        self._seed(["A", "B"])
        lib = [[_lib_book("A", "書A")], None, None]  # 沒有總數：無法證明取齊
        self._patch_client(lambda req: httpx.Response(200, json=lib))
        res = service.scan(self.cfg, log=lambda s: None)
        self.assertTrue(all(b.in_library for b in res.manifest.books.values()))

    def test_bulk_removal_is_treated_as_suspicious(self):
        ids = [f"V{i}" for i in range(12)]
        self._seed(ids)
        res = self._scan(ids[:4])  # 一次 8/12 不在書庫
        self.assertTrue(all(b.in_library for b in res.manifest.books.values()))

    def test_empty_response_does_not_mark_everything_inactive(self):
        self._seed(["A", "B"])
        self._patch_client(lambda req: httpx.Response(200, json=[[], None, None]))
        res = service.scan(self.cfg, log=lambda s: None)
        self.assertTrue(all(b.in_library for b in res.manifest.books.values()))

    def test_export_skips_inactive_books(self):
        from openshelf.manifest import BookEntry

        m = Manifest(self.out / "manifest.json")
        m.upsert(BookEntry(volume_id="X", title="書X", in_library=False))
        m.save()
        calls = []
        self._patch_client(lambda req: calls.append(1) or httpx.Response(200, content=EPUB))
        cache = {"X": [ExportOption(fmt="epub", url="https://x/x")]}
        res = service.export(self.cfg, "epub", True, option_cache=cache, log=lambda s: None)
        self.assertEqual((res.done, res.failed, calls), (0, 0, []))

    def test_reports_show_inactive(self):
        self._seed(["A", "B"])
        res = self._scan(["A"])
        text = (self.out / service.REPORT_NAME).read_text(encoding="utf-8-sig")
        self.assertIn("已下架", text)
        import csv

        with service.write_csv(res.manifest, self.cfg).open(encoding="utf-8-sig", newline="") as fh:
            rows = {r[8]: r for r in csv.reader(fh)}
        self.assertEqual(rows["B"][9], "已下架")
        self.assertEqual(rows["A"][9], "在書庫")

    def test_old_manifest_without_new_fields_loads(self):
        import json

        (self.out / "manifest.json").write_text(json.dumps(
            {"books": {"A": {"volume_id": "A", "title": "舊", "future_field": 1}}}),
            encoding="utf-8")
        e = Manifest.load(self.out / "manifest.json").get("A")
        self.assertTrue(e.in_library)


class ExportFlow(_Env):
    def _manifest(self, books):
        m = Manifest(self.out / "manifest.json")
        from openshelf.manifest import BookEntry

        for vid, title in books:
            m.upsert(BookEntry(volume_id=vid, title=title, author="作者"))
        m.save()

    def test_colliding_normalized_names_do_not_overwrite(self):
        self._manifest([("A", "A/B"), ("B", "A:B")])
        cache = {
            "A": [ExportOption(fmt="epub", url="https://x/a")],
            "B": [ExportOption(fmt="epub", url="https://x/b")],
        }
        self._patch_client(lambda req: httpx.Response(200, content=EPUB))
        res = service.export(self.cfg, "epub", True, option_cache=cache, log=lambda s: None)
        self.assertEqual(res.done, 2)
        m = Manifest.load(self.out / "manifest.json")
        self.assertNotEqual(m.get("A").file_path, m.get("B").file_path)
        for vid in ("A", "B"):
            self.assertTrue((self.out / m.get(vid).file_path).exists())

    def test_epub_failure_falls_back_to_pdf(self):
        self._manifest([("A", "書A")])
        cache = {"A": [ExportOption(fmt="epub", url="https://x/a.epub"),
                       ExportOption(fmt="pdf", url="https://x/a.pdf")]}

        def handler(req):
            if str(req.url).endswith(".epub"):
                return httpx.Response(404)
            return httpx.Response(200, content=PDF)

        self._patch_client(handler)
        res = service.export(self.cfg, "epub", True, option_cache=cache, log=lambda s: None)
        self.assertEqual(res.done, 1)
        e = Manifest.load(self.out / "manifest.json").get("A")
        self.assertTrue(e.file_path.endswith(".pdf"))
        self.assertEqual(e.note, "")

    def test_failure_marks_failed_with_note_and_leaves_no_part_file(self):
        self._manifest([("A", "書A")])
        cache = {"A": [ExportOption(fmt="epub", url="https://x/a.epub")]}
        self._patch_client(lambda req: httpx.Response(200, content=b"<html>login</html>" * 2000))
        res = service.export(self.cfg, "epub", True, option_cache=cache, log=lambda s: None)
        self.assertEqual(res.failed, 1)
        e = Manifest.load(self.out / "manifest.json").get("A")
        self.assertEqual(e.category, "failed")
        self.assertIn("VerifyError", e.note)
        self.assertEqual(list(self.out.glob("*.part")), [])

    def test_refresh_failure_keeps_old_file(self):
        self._manifest([("A", "書A")])
        old = self.out / "書A - 作者.epub"
        old.write_bytes(EPUB)
        m = Manifest.load(self.out / "manifest.json")
        e = m.get("A")
        e.category, e.file_path = "acsm", old.name
        e.downloaded_at = "2000-01-01T00:00:00+00:00"
        m.upsert(e)
        m.save()
        cache = {"A": [ExportOption(fmt="acsm", url="https://x/a.acsm")]}
        self._patch_client(lambda req: httpx.Response(500))
        res = service.export(self.cfg, "epub", True, option_cache=cache,
                             log=lambda s: None, refresh_acsm=True)
        self.assertEqual(res.failed, 1)
        e = Manifest.load(self.out / "manifest.json").get("A")
        self.assertEqual(e.category, "acsm")
        self.assertTrue(e.note.startswith("refresh failed"))
        self.assertTrue(old.exists())

    def test_session_expired_aborts_whole_batch(self):
        self._manifest([("A", "書A"), ("B", "書B")])
        cache = {v: [ExportOption(fmt="epub", url=f"https://x/{v}")] for v in "AB"}
        calls = []

        def handler(req):
            calls.append(str(req.url))
            return httpx.Response(401)

        self._patch_client(handler)
        with self.assertRaises(SessionExpired):
            service.export(self.cfg, "epub", True, option_cache=cache, log=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_stop_before_first_book_writes_nothing(self):
        self._manifest([("A", "書A")])
        cache = {"A": [ExportOption(fmt="epub", url="https://x/a")]}
        self._patch_client(lambda req: httpx.Response(200, content=EPUB))
        res = service.export(self.cfg, "epub", True, option_cache=cache,
                             log=lambda s: None, should_stop=lambda: True)
        self.assertEqual(res.done, 0)
        self.assertEqual(list(self.out.glob("*.epub")), [])
        self.assertEqual(list(self.out.glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
