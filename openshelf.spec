# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包設定：單檔、視窗模式（無主控台）。

在「目標作業系統」上執行才會產出該系統的執行檔（PyInstaller 非跨平台編譯）：
    pip install -e ".[gui,build]"
    pyinstaller openshelf.spec --noconfirm

登入優先使用本機 Chrome / Edge。只有需要 Playwright 內建 Chromium fallback 時，
才需見 README「打包成 .exe」一節，將 Chromium 放到 exe 旁的 ms-playwright/。
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all

_here = os.path.dirname(os.path.abspath(SPEC))
_icon_ico = os.path.join(_here, "assets", "openshelf.ico")
_icon_icns = os.path.join(_here, "assets", "openshelf.icns")
_icon_png = os.path.join(_here, "assets", "openshelf.png")

# 各平台用對應的 icon 格式：Windows .ico、macOS .icns、其餘 .png
if sys.platform == "darwin":
    _icon = _icon_icns
elif sys.platform.startswith("win"):
    _icon = _icon_ico
else:
    _icon = _icon_png

# 視窗 icon（PNG）一併打包，frozen 時由 sys._MEIPASS/assets 取用
datas = [(_icon_png, "assets")]
binaries = []
hiddenimports = []

# Playwright 的 node driver 與套件資料一併帶入（瀏覽器本體不在此）
for _pkg in ("playwright",):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h


a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OpenShelf",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

# macOS：再包成可點擊的 .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="OpenShelf.app",
        icon=_icon_icns,
        bundle_identifier="com.sanhsien.openshelf",
    )
