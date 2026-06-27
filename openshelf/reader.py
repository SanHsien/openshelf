"""無 DRM EPUB/PDF 閱讀器交接。

支援把 OpenShelf 已下載且分類為 drm_free 的 EPUB/PDF 交給 ADE 或系統
預設程式開啟。不處理 .acsm，不移除任何保護。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .manifest import BookEntry, Manifest, now_iso

OpenPath = Callable[[Path], None]

READER_REPORT_NAME = "EPUB-PDF交接報表.txt"
_COMMON_ADE = (
    Path(r"C:\Program Files\Adobe\Adobe Digital Editions 4.5\DigitalEditions.exe"),
    Path(r"C:\Program Files (x86)\Adobe\Adobe Digital Editions 4.5\DigitalEditions.exe"),
)


@dataclass
class ReaderItem:
    book: BookEntry
    path: Path


@dataclass
class ReaderPlan:
    openable: list[ReaderItem] = field(default_factory=list)
    missing: list[BookEntry] = field(default_factory=list)
    skipped: list[BookEntry] = field(default_factory=list)


@dataclass
class ReaderOpenResult:
    opened: int = 0
    dry_run: bool = False
    target: str = "ade"
    plan: ReaderPlan = field(default_factory=ReaderPlan)


def find_ade(config: Config) -> Path | None:
    """找出 ADE executable；找不到時回傳 None，交給系統預設程式。"""
    if config.ade_path:
        if config.ade_path.is_file():
            return config.ade_path
        raise FileNotFoundError(f"找不到 ADE：{config.ade_path}")

    for path in _COMMON_ADE:
        if path.is_file():
            return path
    return None


def build_plan(manifest: Manifest, config: Config) -> ReaderPlan:
    """依 manifest 建立無 DRM EPUB/PDF 交接計畫。"""
    plan = ReaderPlan()
    for book in manifest.books.values():
        if book.category == "drm_free" and book.file_path:
            path = config.output_dir / book.file_path
            if path.is_file():
                plan.openable.append(ReaderItem(book=book, path=path))
            else:
                plan.missing.append(book)
        else:
            plan.skipped.append(book)
    return plan


def open_drm_free(
    config: Config,
    manifest: Manifest,
    target: str = "ade",
    dry_run: bool = False,
    opener: OpenPath | None = None,
) -> ReaderOpenResult:
    """批次開啟已下載的無 DRM EPUB/PDF。"""
    plan = build_plan(manifest, config)
    if dry_run:
        return ReaderOpenResult(opened=0, dry_run=True, target=target, plan=plan)

    open_path = opener or _target_opener(config, target)
    opened = 0
    for item in plan.openable:
        open_path(item.path)
        opened += 1
    return ReaderOpenResult(opened=opened, dry_run=False, target=target, plan=plan)


def write_report(manifest: Manifest, config: Config, target: str = "ade") -> Path:
    """輸出無 DRM EPUB/PDF 交接報表。"""
    plan = build_plan(manifest, config)
    path = config.output_dir / READER_REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)

    target_label = "ADE" if target == "ade" else "系統預設程式"
    lines: list[str] = []
    add = lines.append
    add("OpenShelf EPUB/PDF 交接報表")
    add(f"目標：{target_label}")
    add(f"產生時間：{now_iso()}")
    add("=" * 48)
    add("")
    add("【統計】")
    add(f"  可交接：{len(plan.openable)}")
    add(f"  檔案遺失（manifest 有記錄但檔案不存在）：{len(plan.missing)}")
    add(f"  其他狀態（ACSM／無法匯出／失敗／待下載）：{len(plan.skipped)}")
    add("")

    add("【可交接的 EPUB/PDF】")
    if plan.openable:
        for item in plan.openable:
            add(f"  + {_book_label(item.book)}")
            add(f"      {item.path}")
    else:
        add("  （無）")
    add("")

    add("【檔案遺失】")
    if plan.missing:
        for book in plan.missing:
            add(f"  ! {_book_label(book)}")
            if book.file_path:
                add(f"      {config.output_dir / book.file_path}")
    else:
        add("  （無）")
    add("")

    path.write_text("\n".join(lines), encoding="utf-8-sig")
    return path


def _target_opener(config: Config, target: str) -> OpenPath:
    if target == "ade":
        ade = find_ade(config)
        if ade is not None:
            return lambda path: subprocess.Popen([str(ade), str(path)])
    return _open_default


def _open_default(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    else:
        subprocess.run(["xdg-open", str(path)], check=True)


def _book_label(book: BookEntry) -> str:
    label = book.title or book.volume_id
    if book.author:
        label += f" - {book.author}"
    return label
