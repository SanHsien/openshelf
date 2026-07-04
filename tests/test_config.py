"""config：讀檔、預設值、路徑解析。"""

import tempfile
import unittest
from pathlib import Path

from openshelf.config import load_config


class ConfigTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "config.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_overrides_and_defaults(self):
        p = self._write('output_dir = "books"\nthrottle_seconds = 5\n')
        cfg = load_config(p)
        # 覆寫值
        self.assertEqual(cfg.output_dir.name, "books")
        self.assertEqual(cfg.throttle_seconds, 5.0)
        # 未列出的採預設
        self.assertEqual(cfg.download_retries, 3)
        self.assertEqual(cfg.acsm_valid_days, 7)
        self.assertTrue(cfg.include_acsm)
        self.assertIsNone(cfg.calibredb_path)
        self.assertIsNone(cfg.calibre_library)
        self.assertIsNone(cfg.ade_path)

    def test_paths_relative_to_config(self):
        p = self._write(
            'output_dir = "out"\n'
            'calibredb_path = "Calibre2/calibredb.exe"\n'
            'calibre_library = "Calibre Library"\n'
            'ade_path = "ADE/DigitalEditions.exe"\n'
        )
        cfg = load_config(p)
        self.assertEqual(cfg.output_dir.parent, p.parent)
        self.assertEqual(cfg.manifest_path, cfg.output_dir / "manifest.json")
        self.assertEqual(cfg.calibredb_path, p.parent / "Calibre2" / "calibredb.exe")
        self.assertEqual(cfg.calibre_library, p.parent / "Calibre Library")
        self.assertEqual(cfg.ade_path, p.parent / "ADE" / "DigitalEditions.exe")

    def test_invalid_prefer_format_falls_back(self):
        p = self._write('prefer_format = "mobi"\n')
        self.assertEqual(load_config(p).prefer_format, "epub")


if __name__ == "__main__":
    unittest.main()
