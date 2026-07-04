"""manifest.json 讀寫——單一事實來源（續傳、跳過、報表皆依此）。

分類詞彙：
    drm_free   可直接下載 EPUB/PDF
    acsm       僅提供 ACSM 領取，已下載 .acsm，需以 ADE 開啟
    no_export  無任何匯出選項，只記錄
    failed     流程出錯，待重試
    pending    已枚舉、尚未下載（scan 後、export 前的暫態）
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = {"drm_free", "acsm", "no_export", "failed", "pending"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    """目前 UTC 時間（ISO 8601），供其他模組記錄時間戳。"""
    return _now()


@dataclass
class BookEntry:
    volume_id: str
    title: str = ""
    author: str = ""
    publisher: str = ""  # 出版社（同名書辨識用）
    published: str = ""  # 出版日期（同名書辨識用）
    cover_url: str = ""  # 封面縮圖網址（書庫 metadata；缺漏時 UI 以 volume_id 推導）
    category: str = "pending"
    file_path: str | None = None  # 相對 output_dir 的下載檔名
    downloaded_at: str = ""  # 實際下載時間（.acsm 時效判斷用）
    acsm_opened_at: str = ""  # 送交 ADE / 系統預設程式的時間；非 ADE 成功匯入確認
    note: str = ""
    updated_at: str = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()


class Manifest:
    """以 volume_id 為鍵的書目集合。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.books: dict[str, BookEntry] = {}

    # ---- 持久化 -------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "Manifest":
        m = cls(path)
        if m.path.is_file():
            raw = json.loads(m.path.read_text(encoding="utf-8"))
            for vid, entry in raw.get("books", {}).items():
                m.books[vid] = BookEntry(**entry)
        return m

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _now(),
            "books": {vid: asdict(b) for vid, b in self.books.items()},
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)

    # ---- 操作 ---------------------------------------------------
    def upsert(self, entry: BookEntry) -> BookEntry:
        entry.touch()
        self.books[entry.volume_id] = entry
        return entry

    def get(self, volume_id: str) -> BookEntry | None:
        return self.books.get(volume_id)

    def is_downloaded(self, volume_id: str, output_dir: Path) -> bool:
        """已成功下載（drm_free/acsm 且檔案存在）視為可跳過。"""
        b = self.books.get(volume_id)
        if not b or b.category not in {"drm_free", "acsm"} or not b.file_path:
            return False
        return (output_dir / b.file_path).is_file()

    # ---- 報表 ---------------------------------------------------
    def counts(self) -> dict[str, int]:
        result = {c: 0 for c in CATEGORIES}
        for b in self.books.values():
            result[b.category] = result.get(b.category, 0) + 1
        result["total"] = len(self.books)
        return result
