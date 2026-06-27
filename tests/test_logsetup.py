"""logsetup：日誌寫入 output/openshelf.log。"""

import tempfile
import unittest
from pathlib import Path

from openshelf.logsetup import LOG_NAME, get_logger


class LogSetup(unittest.TestCase):
    def test_writes_to_file(self):
        out = Path(tempfile.mkdtemp())
        logger = get_logger(out)
        logger.info("枚舉：測試書 → drm_free")
        for h in logger.handlers:
            h.flush()
        log_path = out / LOG_NAME
        self.assertTrue(log_path.exists())
        text = log_path.read_text(encoding="utf-8")
        self.assertIn("測試書", text)
        self.assertIn("INFO", text)

    def test_repoints_on_new_dir(self):
        a = Path(tempfile.mkdtemp())
        b = Path(tempfile.mkdtemp())
        get_logger(a).info("to-a")
        logger = get_logger(b)
        logger.info("to-b")
        for h in logger.handlers:
            h.flush()
        self.assertIn("to-b", (b / LOG_NAME).read_text(encoding="utf-8"))
        # 切換目錄後，新訊息不應再寫進舊檔
        self.assertNotIn("to-b", (a / LOG_NAME).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
