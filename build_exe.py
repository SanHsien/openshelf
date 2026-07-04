"""在本機建置 OpenShelf 單檔執行檔。

注意：PyInstaller 非跨平台編譯——在 Windows 上跑才會得到 .exe，
在 macOS / Linux 上跑得到對應平台的執行檔。產物在 dist/ 下。

用法：
    pip install -e ".[gui,build]"
    python build_exe.py

若要退回 Playwright 內建 Chromium 才需要另跑 `playwright install chromium`；
登入預設會優先使用本機 Chrome / Edge。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

# Windows 主控台預設可能是 cp1252/cp950，直接 print 中文會 UnicodeEncodeError。
# 強制以 UTF-8 輸出（保留中文訊息），失敗則忽略。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


def _check_deps() -> bool:
    missing = [
        name
        for name in ("PyInstaller", "PySide6")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        print("缺少打包相依：" + "、".join(missing))
        print('請先安裝：pip install -e ".[gui,build]"')
        return False
    return True


def main() -> int:
    if not _check_deps():
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "openshelf.spec", "--noconfirm"]
    print("執行：", " ".join(cmd))
    return subprocess.run(cmd, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
