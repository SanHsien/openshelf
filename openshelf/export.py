"""下載、命名與覆核。

命名：`書名 - 作者.<副檔名>`，去除檔名非法字元；同名書以 volume_id 區別。
覆核：
  - 大小檢查（.acsm 應為小 XML，書檔應明顯較大）。
  - EPUB/PDF 檢查檔頭魔術位元組，攔截「下載到登入頁/錯誤頁」的情況。
  - .acsm 僅檢查大小，**不檢視其內容**（遵守邊界：不解析 ACSM）。
下載失敗會依設定重試（網路錯誤／5xx 才重試；401/403 與覆核失敗不重試）。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

from .playbooks import ExportOption, download
from .session import SessionExpired

# .acsm 是小型 XML 憑證，書檔遠大於此。用門檻做誤判保護。
ACSM_MAX_BYTES = 64 * 1024  # 64 KB 以上幾乎不會是 acsm
BOOK_MIN_BYTES = 16 * 1024  # 書檔通常遠大於此

# 書檔的檔頭魔術位元組（.acsm 不檢視內容，故不列入）
_MAGIC = {"epub": b"PK\x03\x04", "pdf": b"%PDF-"}

_ILLEGAL = re.compile(r'[\\/:*?"<>|\n\r\t]+')
_MAX_STEM = 180
_MAX_DISAMBIGUATOR = 80


def safe_filename(
    title: str, author: str, ext: str, disambiguator: str | None = None
) -> str:
    title = _ILLEGAL.sub("_", title).strip() or "untitled"
    author = _ILLEGAL.sub("_", author).strip()
    base = f"{title} - {author}" if author else title
    suffix = ""
    if disambiguator:
        disambiguator = _ILLEGAL.sub("_", disambiguator).strip()
        if disambiguator:
            disambiguator = disambiguator[:_MAX_DISAMBIGUATOR].rstrip(". ")
            suffix = f" [{disambiguator}]"
    if suffix:
        base_limit = max(1, _MAX_STEM - len(suffix))
        stem = base[:base_limit].rstrip(". ") + suffix
    else:
        stem = base[:_MAX_STEM].rstrip(". ")  # 避免過長與結尾點
    return f"{stem}.{ext}"


class VerifyError(RuntimeError):
    pass


def _verify(path: Path, fmt: str) -> None:
    size = path.stat().st_size
    if size == 0:
        raise VerifyError("下載檔為空")
    if fmt == "acsm":
        if size > ACSM_MAX_BYTES:
            raise VerifyError(f".acsm 過大（{size} bytes），疑似誤判")
        return
    if size < BOOK_MIN_BYTES:
        raise VerifyError(f"{fmt} 過小（{size} bytes），疑似誤判")
    magic = _MAGIC.get(fmt)
    if magic:
        with open(path, "rb") as fh:
            head = fh.read(64)
        if head[: len(magic)] != magic:
            preview = head.decode("utf-8", "replace").replace("\r", " ").replace("\n", " ")
            raise VerifyError(
                f"{fmt} 檔頭不符，疑似下載到登入頁或錯誤回應（開頭：{preview!r}）"
            )


def download_option(
    client: httpx.Client,
    option: ExportOption,
    output_dir: Path,
    title: str,
    author: str,
    retries: int = 3,
    disambiguator: str | None = None,
) -> str:
    """下載單一格式，回傳相對 output_dir 的檔名。失敗丟例外。

    覆核失敗（VerifyError）與認證失效（SessionExpired）不重試；
    網路錯誤與 5xx 才重試，採指數退避。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = option.fmt.lower()
    filename = safe_filename(title, author, fmt, disambiguator)
    dest = output_dir / filename
    tmp = dest.with_suffix(dest.suffix + ".part")

    attempts = max(1, retries)
    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            download(client, option.url, tmp)
            _verify(tmp, fmt)
            tmp.replace(dest)
            return filename
        except (VerifyError, SessionExpired):
            if tmp.exists():
                tmp.unlink()
            raise
        except httpx.HTTPStatusError as e:
            if tmp.exists():
                tmp.unlink()
            if e.response.status_code < 500:
                raise  # 4xx 不重試
            last_err = e
        except httpx.HTTPError as e:  # 連線／逾時等傳輸錯誤
            if tmp.exists():
                tmp.unlink()
            last_err = e
        if attempt < attempts - 1:
            time.sleep(2 ** attempt)  # 1s, 2s, 4s…
    raise last_err if last_err else RuntimeError("下載失敗")
