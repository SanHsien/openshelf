"""acsm：批次交接 .acsm 到系統預設程式。"""

import tempfile
import unittest
from pathlib import Path

from openshelf.acsm import build_plan, open_acsm, write_report
from openshelf.config import Config
from openshelf.manifest import BookEntry, Manifest


def _cfg(out: Path) -> Config:
    return Config(
        base_dir=out,
        output_dir=out,
        profile_dir=out,
        storage_state=out,
        prefer_format="epub",
        include_acsm=True,
        throttle_seconds=0,
        download_timeout=1,
        download_retries=1,
        acsm_valid_days=7,
        calibredb_path=None,
        calibre_library=None,
        ade_path=None,
    )


def _book(vid, category, file_path=None, title=None):
    return BookEntry(
        volume_id=vid,
        title=title or vid,
        author="作者",
        category=category,
        file_path=file_path,
    )


class AcsmPlanTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.manifest = Manifest(self.dir / "manifest.json")
        (self.dir / "ok.acsm").write_bytes(b"<fulfillmentToken/>")
        self.manifest.books["A"] = _book("A", "acsm", "ok.acsm")
        self.manifest.books["B"] = _book("B", "acsm", "missing.acsm")
        self.manifest.books["C"] = _book("C", "drm_free", "book.epub")
        self.manifest.books["D"] = _book("D", "failed")

    def test_build_plan_only_acsm(self):
        plan = build_plan(self.manifest, _cfg(self.dir))
        self.assertEqual([i.book.volume_id for i in plan.openable], ["A"])
        self.assertEqual([b.volume_id for b in plan.missing], ["B"])
        self.assertEqual([b.volume_id for b in plan.skipped], ["C", "D"])

    def test_open_uses_only_existing_acsm(self):
        opened = []

        def opener(path):
            opened.append(path)

        result = open_acsm(_cfg(self.dir), self.manifest, opener=opener)

        self.assertEqual(result.opened, 1)
        self.assertEqual(opened, [self.dir / "ok.acsm"])
        self.assertTrue(self.manifest.books["A"].acsm_opened_at)

    def test_open_limit_and_skip_opened_by_default(self):
        (self.dir / "ok2.acsm").write_bytes(b"<fulfillmentToken/>")
        self.manifest.books["E"] = _book("E", "acsm", "ok2.acsm")
        opened = []

        def opener(path):
            opened.append(path)

        first = open_acsm(_cfg(self.dir), self.manifest, limit=1, opener=opener)
        self.assertEqual(first.opened, 1)
        self.assertEqual(opened, [self.dir / "ok.acsm"])

        second = open_acsm(_cfg(self.dir), self.manifest, limit=1, opener=opener)
        self.assertEqual(second.opened, 1)
        self.assertEqual(opened, [self.dir / "ok.acsm", self.dir / "ok2.acsm"])

    def test_include_opened_reopens_previous_handoff(self):
        self.manifest.books["A"].acsm_opened_at = "2026-06-29T00:00:00+00:00"
        opened = []

        result = open_acsm(
            _cfg(self.dir),
            self.manifest,
            include_opened=True,
            opener=lambda path: opened.append(path),
        )

        self.assertEqual(result.opened, 1)
        self.assertEqual(opened, [self.dir / "ok.acsm"])

    def test_dry_run_does_not_open(self):
        opened = []
        result = open_acsm(
            _cfg(self.dir),
            self.manifest,
            dry_run=True,
            opener=lambda path: opened.append(path),
        )
        self.assertEqual(result.opened, 0)
        self.assertTrue(result.dry_run)
        self.assertEqual(opened, [])
        self.assertEqual(len(result.plan.openable), 1)

    def test_report(self):
        path = write_report(self.manifest, _cfg(self.dir))
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("OpenShelf ACSM 交接報表", text)
        self.assertIn("ok.acsm", text)
        self.assertIn("檔案遺失", text)


if __name__ == "__main__":
    unittest.main()
