"""把 Playwright 保存的 storage_state 載入為帶登入態的 httpx client。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from .config import Config

# 貼近一般瀏覽器的標頭，降低被當成異常流量的機率
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


class NotLoggedIn(RuntimeError):
    """找不到登入態，需先執行 openshelf login。"""


class SessionExpired(RuntimeError):
    """登入態被伺服器拒絕（401/403），多半已過期，需重新 openshelf login。"""


def _load_cookies(storage_state: Path) -> list[dict]:
    if not storage_state.is_file():
        raise NotLoggedIn(
            f"找不到登入態 {storage_state}，請先執行：openshelf login"
        )
    data = json.loads(storage_state.read_text(encoding="utf-8"))
    return data.get("cookies", [])


def check_storage_permissions(storage_state: Path) -> str | None:
    """檢查登入態檔案權限（POSIX 系統）。

    若在 POSIX 系統（非 Windows）上且群組或其他使用者具有存取權限（mode & 0o077 != 0），
    回傳警告文字；若權限正常、非 POSIX 系統（Windows ACL 另列中期）或檔案不存在則回傳 None。
    """
    if sys.platform.startswith("win"):
        return None
    if not storage_state.is_file():
        return None
    try:
        mode = storage_state.stat().st_mode
    except OSError:
        return None
    if mode & 0o077:
        current_octal = oct(mode & 0o777)
        return (
            f"登入態檔案 {storage_state} 權限過寬（{current_octal}），"
            f"其他本機使用者可能可讀取敏感 cookie；建議設為 600（chmod 600 {storage_state}）。"
        )
    return None


def build_client(config: Config) -> httpx.Client:
    """建立沿用登入態 cookies 的 httpx client。"""
    cookies = _load_cookies(config.storage_state)
    jar = httpx.Cookies()
    for c in cookies:
        jar.set(
            name=c["name"],
            value=c["value"],
            domain=c.get("domain", "").lstrip("."),
            path=c.get("path", "/"),
        )
    return httpx.Client(
        headers=DEFAULT_HEADERS,
        cookies=jar,
        timeout=config.download_timeout,
        follow_redirects=True,
    )
