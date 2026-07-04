"""OpenShelf 桌面應用進入點（供 PyInstaller 打包成單一執行檔）。

打包後（frozen）Chromium 來源的尋找順序：
1. exe 旁的 `ms-playwright/`（若存在）→ 可攜帶散布，整包帶走即可。
2. 否則沿用系統預設的 Playwright 瀏覽器快取（%LOCALAPPDATA%\\ms-playwright），
   也就是本機曾 `playwright install chromium` 下載的位置。

登入會優先使用本機 Chrome / Edge；只有退回 Playwright 內建 Chromium 時才用到此設定。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _configure_frozen_runtime() -> None:
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "ms-playwright"
        if bundled.exists():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled))
        # 否則不覆蓋，讓 Playwright 用系統預設快取，自動找到已安裝的 Chromium


def main() -> int:
    _configure_frozen_runtime()
    from openshelf.config import load_config
    from openshelf.ui.main_window import run

    return run(load_config())


if __name__ == "__main__":
    raise SystemExit(main())
