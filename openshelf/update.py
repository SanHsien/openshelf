"""檢查 GitHub Releases 是否有新版（只比對版本、提示下載，不自動覆寫）。

純函式（版本解析、比較）放這裡方便測試；實際的網路請求由 GUI 以
非同步方式發出，本模組不主動連網。
"""

from __future__ import annotations

import re

OWNER_REPO = "SanHsien/openshelf"
RELEASES_API = f"https://api.github.com/repos/{OWNER_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{OWNER_REPO}/releases"


def parse_version(s: str) -> tuple[int, ...]:
    """把 'v0.4.0' / '0.4.0' 解析成 (0, 4, 0)；無數字回傳空 tuple。"""
    nums = re.findall(r"\d+", (s or "").strip().lstrip("vV"))
    return tuple(int(n) for n in nums[:3])


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新（語意化版本，數字比較）。"""
    lv, cv = parse_version(latest), parse_version(current)
    if not lv:
        return False
    n = max(len(lv), len(cv))
    lv += (0,) * (n - len(lv))
    cv += (0,) * (n - len(cv))
    return lv > cv


def tag_from_release_json(data) -> str:
    """從 GitHub releases/latest 回應取出 tag_name。"""
    if isinstance(data, dict):
        return str(data.get("tag_name") or "")
    return ""
