"""一次性瀏覽器登入與登入態保存。

Google 不允許腳本帶帳密登入；這裡只開一個真實瀏覽器視窗讓使用者手動登入，
登入完成後把登入態（cookies）存成 storage_state，供之後的 HTTP 流程沿用。
**程式不經手任何帳號密碼。**
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import Config

PLAY_BOOKS_URL = "https://play.google.com/books"
# 登入完成的判斷依據：出現使用者帳號元素或書庫內容；保守起見以使用者手動確認為主。

# 啟動瀏覽器的優先順序：本機真 Chrome → Edge → Playwright 內建 Chromium。
# Google 會擋帶自動化旗標的內建 Chromium（「瀏覽器不安全」），用真 Chrome 較能通過。
_CHANNELS: tuple[str | None, ...] = ("chrome", "msedge", None)


def _launch(p, config: Config, headless: bool, channel: str | None):
    kwargs = dict(
        user_data_dir=str(config.profile_dir),
        headless=headless,
        accept_downloads=True,
        # 移除最常被偵測的自動化指紋，讓使用者能在自己帳號手動登入
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    if channel:
        kwargs["channel"] = channel
    return p.chromium.launch_persistent_context(**kwargs)


def login(
    config: Config,
    headless: bool = False,
    confirm: Callable[[], None] | None = None,
) -> Path:
    """開啟瀏覽器供手動登入，存下 storage_state，回傳其路徑。

    使用持久化 context（user_data_dir=profile_dir），下次登入態多半仍在，
    只需在視窗確認即可。優先用本機真 Chrome／Edge，降低 Google 對自動化
    瀏覽器的登入封鎖；都沒有才退回 Playwright 內建 Chromium。

    confirm：等待使用者完成登入的回呼。CLI 預設用 stdin（按 Enter）；
    GUI 可傳入會阻塞到使用者按下「完成」的回呼。
    """
    # 延遲匯入，未安裝 Playwright 時也能 import 其他模組
    from playwright.sync_api import sync_playwright

    config.profile_dir.mkdir(parents=True, exist_ok=True)
    config.storage_state.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = None
        used = None
        last_error: Exception | None = None
        for channel in _CHANNELS:
            try:
                context = _launch(p, config, headless, channel)
                used = channel or "內建 chromium"
                break
            except Exception as e:  # noqa: BLE001 — 該 channel 不存在就試下一個
                last_error = e
        if context is None:
            raise RuntimeError(
                f"無法啟動任何瀏覽器（Chrome／Edge／內建 Chromium 皆失敗）：{last_error}"
            )
        print(f"登入瀏覽器：{used}")

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PLAY_BOOKS_URL, wait_until="domcontentloaded")

        if confirm is not None:
            confirm()
        else:
            print(
                "\n請在開啟的瀏覽器視窗手動登入你的 Google 帳號並開啟 Play 圖書，\n"
                "看到自己的書庫後回到這裡按 Enter 完成…"
            )
            try:
                input()
            except EOFError:
                # 非互動環境：給予一段時間後仍以當前狀態存檔
                page.wait_for_timeout(60_000)

        context.storage_state(path=str(config.storage_state))
        context.close()

    return config.storage_state
