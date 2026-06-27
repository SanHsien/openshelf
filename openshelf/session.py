"""把 Playwright 保存的 storage_state 載入為帶登入態的 httpx client。"""

from __future__ import annotations

import json
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
