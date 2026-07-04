"""依匯出選項判斷分類：drm_free / acsm / no_export。

規則：
    有 epub 或 pdf 可下載      -> drm_free
    沒有書檔、但有 acsm        -> acsm
    什麼都沒有                  -> no_export
"""

from __future__ import annotations

from .playbooks import ExportOption

BOOK_FORMATS = {"epub", "pdf"}


def classify(options: list[ExportOption]) -> str:
    formats = {o.fmt.lower() for o in options}
    if formats & BOOK_FORMATS:
        return "drm_free"
    if "acsm" in formats:
        return "acsm"
    return "no_export"


def pick_book_option(
    options: list[ExportOption], prefer_format: str
) -> ExportOption | None:
    """drm_free 書：依偏好挑 EPUB/PDF，無偏好格式時退回另一種。"""
    by_fmt = {o.fmt.lower(): o for o in options}
    order = (
        ["epub", "pdf"] if prefer_format == "epub" else ["pdf", "epub"]
    )
    for fmt in order:
        if fmt in by_fmt:
            return by_fmt[fmt]
    return None


def pick_acsm_option(options: list[ExportOption]) -> ExportOption | None:
    for o in options:
        if o.fmt.lower() == "acsm":
            return o
    return None
