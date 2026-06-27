"""結構化日誌：把 scan / export 的訊息附帶時間戳寫到 output/openshelf.log。

供回報問題時附上。日誌落在 output/（已在 .gitignore），不進版控。
"""

from __future__ import annotations

import logging
from pathlib import Path

LOG_NAME = "openshelf.log"


def get_logger(output_dir: Path) -> logging.Logger:
    """取得寫入 output_dir/openshelf.log 的 logger（依目前 output_dir 重設 handler）。"""
    path = Path(output_dir) / LOG_NAME
    want = str(path)
    logger = logging.getLogger("openshelf")
    if getattr(logger, "_openshelf_path", None) != want:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger._openshelf_path = want  # type: ignore[attr-defined]
    return logger
