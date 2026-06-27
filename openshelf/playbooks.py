"""Play Books 後端端點存取層（HTTP-first 的核心）。

書庫枚舉走 Google 私有的 gRPC-Web / protobuf-as-JSON RPC：
    POST https://playbooks-pa.clients6.google.com/$rpc/
         google.internal.play.books.library.v1.LibraryService/SyncUserLibrary

認證沿用網頁版做法：以 SAPISID cookie + 來源網址 + 時間戳計算 SAPISIDHASH，
連同網頁版內嵌的公開 API key 一起送出。回應為位置式 protobuf-as-JSON，
下載 URL 一併內含（無 DRM 為直抓連結，DRM 為 .acsm 領取憑證）。枚舉會自動分頁。

全程只是「以你自己的登入態取得你自己的書庫與官方下載 URL」，
不解析 .acsm、不抽金鑰、不碰任何 DRM 保護。Google 後端改版時只需改本檔。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

import httpx

from .session import SessionExpired

# 網頁版內嵌的公開資訊（非機密；每個 Play Books 網頁都看得到）
API_HOST = "https://playbooks-pa.clients6.google.com"
API_KEY = "AIzaSyCWq1--9JnN9QM7k57Rc_qmt9c0OVy0rME"
ORIGIN = "https://play.google.com"

LIBRARY_METHOD = "google.internal.play.books.library.v1.LibraryService/SyncUserLibrary"
# 觀察到的 SyncUserLibrary 請求 body（位置式 protobuf-as-JSON）；[PAGE_SIZE] 為頁面大小，
# body[8] 為分頁游標（[token, page]）。
_PAGE_SIZE = 400
_MAX_PAGES = 50  # 安全上限，避免游標解讀錯誤造成無限迴圈

# 計算 SAPISIDHASH 時依序嘗試的 cookie（值通常相同）
_SAPISID_COOKIES = ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID")

# SyncUserLibrary 回應中的格式代碼
_FMT_CODE = {1: "epub", 2: "pdf"}


class EndpointNotConfigured(NotImplementedError):
    """端點或回應對應尚未以實際樣本完成（M2 待辦）。"""


@dataclass
class ExportOption:
    """單一可匯出格式。"""

    fmt: str  # "epub" | "pdf" | "acsm"
    url: str  # 取得該檔案的下載 URL


@dataclass
class LibraryBook:
    """書庫中的一本書（枚舉結果）。"""

    volume_id: str
    title: str = ""
    author: str = ""
    publisher: str = ""
    published: str = ""
    cover_url: str = ""
    export_options: list[ExportOption] = field(default_factory=list)


# 封面縮圖：可從書庫 metadata 取得；沒有時用 volume_id 推導 Google Books 公開封面。
# 封面只是書的縮圖圖片，非書本內容，與 DRM 無關。
_COVER_HINTS = ("frontcover", "/books/content", "googleusercontent", "/images/")


def cover_thumb_url(volume_id: str) -> str:
    """以 volume_id 推導 Google Books 公開封面縮圖網址（書庫沒給封面時的備援）。"""
    return (
        "https://books.google.com/books/content"
        f"?id={volume_id}&printsec=frontcover&img=1&zoom=1"
    )


def _iter_strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, list):
        for item in x:
            yield from _iter_strings(item)


def _find_cover_url(info) -> str:
    """從書目 metadata 中找出像封面縮圖的 http(s) 網址；找不到回傳空字串。

    只認封面／縮圖樣式的網址（含 frontcover、/books/content、googleusercontent…），
    不碰任何下載 URL（那些在另一個下載區塊，本函式不掃）。
    """
    for s in _iter_strings(info):
        if not isinstance(s, str) or not re.match(r"https?://", s):
            continue
        low = s.lower()
        if "/books/download/" in low or "output=" in low:  # 保險：排除下載連結
            continue
        if any(h in low for h in _COVER_HINTS):
            return s
    return ""


# ---- 認證與傳輸 -------------------------------------------------
def _get_sapisid(client: httpx.Client) -> str:
    # 同名 cookie 可能存在多個網域（值相同）；直接掃 jar 取第一筆，
    # 避免 client.cookies.get() 在同名多筆時丟 CookieConflict
    for name in _SAPISID_COOKIES:
        for cookie in client.cookies.jar:
            if cookie.name == name and cookie.value:
                return cookie.value
    raise EndpointNotConfigured(
        "登入態中找不到 SAPISID cookie，請重新 openshelf login。"
    )


def _sapisidhash(sapisid: str, origin: str = ORIGIN) -> str:
    """Google 網頁版的 SAPISIDHASH 認證：ts_SHA1("ts SAPISID origin")。"""
    ts = int(time.time())
    digest = hashlib.sha1(f"{ts} {sapisid} {origin}".encode()).hexdigest()
    # 網頁版會同時送三個變體（SAPISID / 1P / 3P），值相同
    return (
        f"SAPISIDHASH {ts}_{digest} "
        f"SAPISID1PHASH {ts}_{digest} "
        f"SAPISID3PHASH {ts}_{digest}"
    )


def _headers(client: httpx.Client) -> dict[str, str]:
    return {
        "Authorization": _sapisidhash(_get_sapisid(client)),
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-AuthUser": "0",
        "Content-Type": "application/json+protobuf",
        "X-User-Agent": "grpc-web-javascript/0.1",
        "Origin": ORIGIN,
        "Referer": ORIGIN + "/",
    }


def _raise_if_expired(status_code: int) -> None:
    if status_code in (401, 403):
        raise SessionExpired(
            "登入態被拒絕（HTTP %d），多半已過期，請重新 openshelf login。" % status_code
        )


def _call(client: httpx.Client, method: str, body) -> list:
    """呼叫一個 $rpc 方法，回傳解析後的 JSON（位置式陣列）。"""
    url = f"{API_HOST}/$rpc/{method}"
    resp = client.post(url, headers=_headers(client), content=json.dumps(body))
    _raise_if_expired(resp.status_code)
    resp.raise_for_status()
    return resp.json()


# ---- 書庫枚舉 ---------------------------------------------------
def _library_body(token: str | None) -> list:
    """組出 SyncUserLibrary 請求 body；token 為上一頁回傳的分頁游標。"""
    body = [None, None, None, None, [_PAGE_SIZE],
            [[[1, 2]], None, [[1, 2, 3]], 1], None, None, [None, 1]]
    if token:
        body[8] = [token, 1]
    return body


def _extract_meta(raw: list) -> tuple[int | None, str | None]:
    """從回應頂層取出（總書數, 分頁游標）。找不到則為 None（退化成單頁）。"""
    total: int | None = None
    token: str | None = None
    if not isinstance(raw, list):
        return total, token
    for el in raw[1:]:  # raw[0] 是書目清單
        if isinstance(el, list) and len(el) == 1 and isinstance(el[0], int):
            total = el[0]
        elif isinstance(el, list) and el and isinstance(el[0], str) and len(el[0]) > 20:
            token = el[0]
    return total, token


def list_library(client: httpx.Client) -> list[LibraryBook]:
    """枚舉整個書庫（自動分頁，直到取齊總數或無法再前進）。"""
    books: list[LibraryBook] = []
    seen: set[str] = set()
    token: str | None = None
    for _ in range(_MAX_PAGES):
        raw = _call(client, LIBRARY_METHOD, _library_body(token))
        page = _parse_library(raw)
        new = [b for b in page if b.volume_id not in seen]
        for b in new:
            seen.add(b.volume_id)
        books.extend(new)

        total, next_token = _extract_meta(raw)
        if not new:  # 沒有新書，停
            break
        if total is not None and len(books) >= total:  # 已取齊
            break
        if not next_token or next_token == token:  # 沒有游標或無法前進
            break
        token = next_token
    return books


def _parse_library(raw: list) -> list[LibraryBook]:
    """把 SyncUserLibrary 回應對應成 LibraryBook。

    回應頂層為陣列，raw[0] 是書目清單；每本書形如
        [ volume_id, [書名, [作者…], …], …, 下載區塊 ]
    下載區塊（每本書的最後一個元素）的第 10 個元素（index 9）含可下載格式。
    """
    if not raw or not isinstance(raw[0], list):
        return []
    books: list[LibraryBook] = []
    for item in raw[0]:
        if not isinstance(item, list) or len(item) < 2:
            continue
        volume_id, info = item[0], item[1]
        if not isinstance(volume_id, str) or not isinstance(info, list):
            continue
        title = info[0] if info and isinstance(info[0], str) else ""
        authors = info[1] if len(info) > 1 and isinstance(info[1], list) else []
        author = ", ".join(a for a in authors if isinstance(a, str))
        publisher = info[2] if len(info) > 2 and isinstance(info[2], str) else ""
        published = info[3] if len(info) > 3 and isinstance(info[3], str) else ""
        cover_url = _find_cover_url(info)
        options = _parse_download_block(item[-1])
        books.append(
            LibraryBook(
                volume_id=volume_id,
                title=title,
                author=author,
                publisher=publisher,
                published=published,
                cover_url=cover_url,
                export_options=options,
            )
        )
    return books


def _parse_download_block(block) -> list[ExportOption]:
    """解析單本書的下載區塊，回傳可下載格式。

    區塊第 10 個元素形如 [[ [fmt, url], [fmt, null, acsm_url] … ]]：
        [fmt, url]            → 無 DRM，直接下載 EPUB/PDF
        [fmt, null, acsm_url] → DRM，下載 .acsm 領取憑證（交給 ADE）
    沒有可下載格式（如試閱本）則回傳空 list（上層分類為 no_export）。
    """
    if not isinstance(block, list) or len(block) < 10:
        return []
    wrapper = block[9]
    if not isinstance(wrapper, list) or not wrapper or not isinstance(wrapper[0], list):
        return []
    options: list[ExportOption] = []
    for entry in wrapper[0]:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        if len(entry) == 2:  # 無 DRM 直接下載
            url, fmt = entry[1], _FMT_CODE.get(entry[0], "epub")
        else:  # ACSM（DRM）
            url, fmt = entry[-1], "acsm"
        if isinstance(url, str) and url:
            options.append(ExportOption(fmt=fmt, url=url))
    return options


def get_export_options(client: httpx.Client, volume_id: str) -> list[ExportOption]:
    """單本匯出選項——書庫枚舉已內含下載 URL，故此處不再另外查詢。"""
    return []


def check_library_endpoint(client: httpx.Client) -> tuple[bool, str]:
    """端點健康檢查：確認 SyncUserLibrary 回應結構仍符合預期。

    Google 改版時回應結構可能變動；此檢查發一次最小請求並驗證結構，
    回傳 (是否正常, 說明)。不解析 .acsm、不碰任何 DRM。
    """
    try:
        raw = _call(client, LIBRARY_METHOD, _library_body(None))
    except SessionExpired as e:
        return False, str(e)
    except httpx.HTTPError as e:
        return False, f"連線或 HTTP 狀態錯誤：{e}"

    if not isinstance(raw, list) or not raw:
        return False, "回應不是預期的陣列，Google 後端可能已改版（請更新 playbooks.py）。"
    if not isinstance(raw[0], list):
        return False, "書目清單結構與預期不符，Google 後端可能已改版（請更新 playbooks.py）。"

    books = _parse_library(raw)
    total, _token = _extract_meta(raw)
    if raw[0] and not books:
        return False, "有書目資料但無法解析，欄位位置可能已變動（請更新 playbooks.py）。"
    total_txt = "未知" if total is None else str(total)
    return True, f"端點正常：本頁可解析 {len(books)} 筆，書庫總數約 {total_txt}。"


# ---- 下載（已實作） --------------------------------------------
def download(client: httpx.Client, url: str, dest_tmp) -> None:
    """串流下載 url 到暫存檔 dest_tmp。

    對 .acsm 而言這只是把官方領取憑證原樣存檔，不做任何解析或轉換。
    """
    with client.stream("GET", url) as resp:
        _raise_if_expired(resp.status_code)
        resp.raise_for_status()
        with open(dest_tmp, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                fh.write(chunk)
