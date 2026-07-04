"""reader：無 DRM EPUB/PDF 可交接 ADE 或系統預設程式。"""

import tempfile
import unittest
from pathlib import Path

from openshelf.config import Config
from openshelf.manifest import BookEntry, Manifest
from openshelf.reader import build_plan, open_drm_free, write_report


def _cfg(out: Path, ade_path: Path | None = None) -> Config:
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
        ade_path=ade_path,
    )


def _book(vid, category, file_path=None):
    return BookEntry(
        volume_id=vid,
        title=vid,
        author="作者",
        category=category,
        file_path=file_path,
    )


class ReaderPlanTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.manifest = Manifest(self.dir / "manifest.json")
        (self.dir / "ok.epub").write_bytes(b"epub")
        self.manifest.books["A"] = _book("A", "drm_free", "ok.epub")
        self.manifest.books["B"] = _book("B", "drm_free", "missing.pdf")
        self.manifest.books["C"] = _book("C", "acsm", "book.acsm")
        self.manifest.books["D"] = _book("D", "failed")

    def test_build_plan_only_drm_free_existing_files(self):
        plan = build_plan(self.manifest, _cfg(self.dir))
        self.assertEqual([i.book.volume_id for i in plan.openable], ["A"])
        self.assertEqual([b.volume_id for b in plan.missing], ["B"])
        self.assertEqual([b.volume_id for b in plan.skipped], ["C", "D"])

    def test_open_uses_only_drm_free_files(self):
        opened = []

        result = open_drm_free(
            _cfg(self.dir),
            self.manifest,
            opener=lambda path: opened.append(path),
        )

        self.assertEqual(result.opened, 1)
        self.assertEqual(opened, [self.dir / "ok.epub"])

    def test_dry_run_does_not_open(self):
        opened = []
        result = open_drm_free(
            _cfg(self.dir),
            self.manifest,
            dry_run=True,
            opener=lambda path: opened.append(path),
        )
        self.assertEqual(result.opened, 0)
        self.assertTrue(result.dry_run)
        self.assertEqual(opened, [])

    def test_report(self):
        path = write_report(self.manifest, _cfg(self.dir), target="ade")
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("OpenShelf EPUB/PDF 交接報表", text)
        self.assertIn("目標：ADE", text)
        self.assertIn("ok.epub", text)


if __name__ == "__main__":
    unittest.main()
