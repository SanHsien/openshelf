"""calibre：只交接無 DRM EPUB/PDF。"""

import tempfile
import unittest
from pathlib import Path

from openshelf.calibre import build_plan, import_drm_free, write_report
from openshelf.config import Config
from openshelf.manifest import BookEntry, Manifest


def _cfg(out: Path, calibredb: Path | None = None) -> Config:
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
        calibredb_path=calibredb,
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


class CalibrePlanTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.manifest = Manifest(self.dir / "manifest.json")
        (self.dir / "ok.epub").write_bytes(b"epub")
        self.manifest.books["A"] = _book("A", "drm_free", "ok.epub")
        self.manifest.books["B"] = _book("B", "drm_free", "missing.pdf")
        self.manifest.books["C"] = _book("C", "acsm", "book.acsm")
        self.manifest.books["D"] = _book("D", "failed")

    def test_build_plan_excludes_acsm(self):
        plan = build_plan(self.manifest, _cfg(self.dir))
        self.assertEqual([i.book.volume_id for i in plan.importable], ["A"])
        self.assertEqual([b.volume_id for b in plan.missing], ["B"])
        self.assertEqual([b.volume_id for b in plan.acsm], ["C"])
        self.assertEqual([b.volume_id for b in plan.skipped], ["D"])

    def test_import_uses_only_drm_free_existing_files(self):
        calls = []
        fake = self.dir / "calibredb.exe"
        fake.write_bytes(b"")

        def run(cmd):
            calls.append(cmd)

        result = import_drm_free(
            _cfg(self.dir, fake),
            self.manifest,
            run_cmd=run,
        )

        self.assertEqual(result.imported, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn(str(self.dir / "ok.epub"), calls[0])
        self.assertNotIn(str(self.dir / "book.acsm"), calls[0])

    def test_dry_run_does_not_require_calibredb(self):
        result = import_drm_free(_cfg(self.dir, self.dir / "missing.exe"), self.manifest, dry_run=True)
        self.assertEqual(result.imported, 0)
        self.assertTrue(result.dry_run)
        self.assertEqual(len(result.plan.importable), 1)

    def test_report(self):
        path = write_report(self.manifest, _cfg(self.dir))
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("可匯入 Calibre", text)
        self.assertIn("ok.epub", text)
        self.assertIn(".acsm 不匯入 Calibre", text)


if __name__ == "__main__":
    unittest.main()
