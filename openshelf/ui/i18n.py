"""輕量介面多語：以「繁中原字串」為鍵，查英文對照。

用法：在介面字串外包一層 tr("登入")。語言為 zh 時回傳原字串，
en 時回傳對照英文（查不到就回原字串，確保不會缺字）。
"""

from __future__ import annotations

import locale

LANGUAGES = ("zh", "en")
_lang = "zh"

# 繁中原字串 → 英文。zh 不需列出（直接回原字串）。
_EN: dict[str, str] = {
    # 視窗 / 群組 / 分頁
    "OpenShelf": "OpenShelf",
    "書庫": "Library",
    "下載": "Download",
    "ACSM": "ACSM",
    "EPUB/PDF": "EPUB/PDF",
    # 按鈕
    "登入": "Sign in",
    "掃描書庫": "Scan library",
    "重試失敗": "Retry failed",
    "停止": "Stop",
    "重新整理": "Refresh",
    "匯出CSV/HTML": "Export CSV/HTML",
    "ℹ 關於": "ℹ About",
    "檢查EPUB/PDF": "Check EPUB/PDF",
    "交接EPUB/PDF": "Hand off EPUB/PDF",
    "EPUB/PDF報表": "EPUB/PDF report",
    "檢查ACSM": "Check ACSM",
    "開啟ACSM": "Open ACSM",
    "ACSM報表": "ACSM report",
    # 核取方塊
    "抓 .acsm": "Fetch .acsm",
    "重抓逾時 .acsm": "Re-fetch stale .acsm",
    "強制重抓 .acsm": "Force re-fetch .acsm",
    "ADE 顯示 E_ADEPT_REQUEST_EXPIRED 時使用：不看有效天數，重新下載官方 .acsm 憑證": (
        "Use when ADE shows E_ADEPT_REQUEST_EXPIRED: ignore validity days and re-download official .acsm tokens"
    ),
    "包含已送出": "Include sent",
    "ADE 當場失敗時使用：重新送出先前已交接的 .acsm": (
        "Use when ADE fails immediately: resend .acsm files that were already handed off"
    ),
    "略過已知失敗": "Skip known failures",
    "顯示封面": "Show covers",
    # 標籤
    "無 DRM 格式": "DRM-free format",
    "目標": "Target",
    "批次": "Batch",
    "一次送給 ADE 的 .acsm 數量；建議分批處理，避免憑證排隊過期": (
        "Number of .acsm files to send to ADE at once; process in batches to avoid queued tokens expiring"
    ),
    "搜尋": "Search",
    "篩選": "Filter",
    "紀錄": "Log",
    "語言": "Language",
    "搜尋 書名／作者／出版社": "Search title / author / publisher",
    # 表頭
    "書名": "Title",
    "作者": "Author",
    "出版社": "Publisher",
    "分類": "Category",
    "檔案": "File",
    "ID": "ID",
    # 篩選 / 分類
    "全部": "All",
    "無 DRM": "DRM-free",
    "無 DRM（EPUB/PDF）": "DRM-free (EPUB/PDF)",
    "DRM（.acsm，需 ADE）": "DRM (.acsm, needs ADE)",
    "無法匯出": "No export",
    "失敗": "Failed",
    "待下載": "Pending",
    # 摘要
    "總計": "Total",
    "Calibre": "Calibre",
    # 提示 / 對話框
    "關於 OpenShelf（版本、作者、GitHub）": "About OpenShelf (version, author, GitHub)",
    "關於 OpenShelf": "About OpenShelf",
    "只重新嘗試先前標記為失敗的書": "Retry only books previously marked as failed",
    "把書庫清單匯出為 CSV 與 HTML 報表並開啟資料夾":
        "Export the library list to CSV and HTML, then open the folder",
    "顯示書籍封面縮圖（需連網抓封面圖片，會快取於 output/.cover_cache）":
        "Show cover thumbnails (fetched online, cached in output/.cover_cache)",
    # 關於對話框
    "版本": "Version",
    "作者": "Author",
    "授權": "License",
    "枚舉並批次匯出 Google Play 圖書：無 DRM 書下載 EPUB/PDF，"
    "DRM 書下載官方 .acsm 供 Adobe Digital Editions 閱讀。<br>"
    "不解析 ACSM、不抽金鑰、不移除任何保護。":
        "Enumerate and batch-export your Google Play Books: DRM-free books as "
        "EPUB/PDF, DRM books as the official .acsm for Adobe Digital Editions.<br>"
        "No ACSM parsing, no key extraction, no protection removal.",
    # 下載佇列
    "處理中": "Processing",
    "目前": "Now",
    "預計剩餘": "ETA",
    "manifest 為空，請先掃描書庫。": "Library is empty — scan the library first.",
    "匯出報表": "Export report",
    # 檢查更新
    "檢查更新": "Check for updates",
    "有新版本": "A new version is available",
    "已是最新版本。": "You're on the latest version.",
    "檢查更新失敗（請稍後再試）。": "Update check failed (please try again later).",
    # 首次啟動導覽
    "歡迎使用 OpenShelf": "Welcome to OpenShelf",
    "開始登入": "Start sign-in",
    "稍後": "Later",
    "三步驟備份你的書庫：<br>"
    "1. <b>登入</b>：在瀏覽器登入一次 Google 帳號<br>"
    "2. <b>掃描書庫</b>：枚舉並分類你的書<br>"
    "3. <b>下載</b>：無 DRM 抓 EPUB/PDF，DRM 抓 .acsm 供 ADE 閱讀<br><br>"
    "現在就開始登入嗎？":
        "Back up your library in three steps:<br>"
        "1. <b>Sign in</b>: sign in to Google once in the browser<br>"
        "2. <b>Scan library</b>: enumerate and classify your books<br>"
        "3. <b>Download</b>: DRM-free as EPUB/PDF, DRM as .acsm for ADE<br><br>"
        "Start signing in now?",
}


def detect_default() -> str:
    """以系統語系猜預設語言：zh* → zh，其餘 → en。"""
    try:
        code = (locale.getdefaultlocale()[0] or "").lower()
    except Exception:  # noqa: BLE001 — 取不到語系就退回英文
        code = ""
    return "zh" if code.startswith("zh") else "en"


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else "zh"


def current_language() -> str:
    return _lang


def tr(zh: str) -> str:
    if _lang == "zh":
        return zh
    return _EN.get(zh, zh)
