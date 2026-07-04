"""ACSM 交接：批次用系統預設程式開啟 .acsm。

本模組只找出 manifest 中分類為 acsm、且檔案存在的項目，交給作業系統
預設程式處理。Windows 上通常會由 Adobe Digital Editions 開啟。
不解析、不改寫、不轉換 .acsm。
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

ACSM_REPORT_NAME = "ACSM交接報表.txt"


@dataclass
class AcsmItem:
    book: BookEntry
    path: Path


@dataclass
class AcsmPlan:
    openable: list[AcsmItem] = field(default_factory=list)
    already_opened: list[AcsmItem] = field(default_factory=list)
    missing: list[BookEntry] = field(default_factory=list)
    skipped: list[BookEntry] = field(default_factory=list)


@dataclass
class AcsmOpenResult:
    opened: int = 0
    dry_run: bool = False
    plan: AcsmPlan = field(default_factory=AcsmPlan)


def build_plan(
    manifest: Manifest,
    config: Config,
    include_opened: bool = False,
) -> AcsmPlan:
    """依 manifest 建立 ACSM 交接計畫。"""
    plan = AcsmPlan()
    for book in manifest.books.values():
        if book.category == "acsm" and book.file_path:
            path = config.output_dir / book.file_path
            if path.is_file():
                item = AcsmItem(book=book, path=path)
                if book.acsm_opened_at and not include_opened:
                    plan.already_opened.append(item)
                else:
                    plan.openable.append(item)
            else:
                plan.missing.append(book)
        else:
            plan.skipped.append(book)
    return plan


def open_acsm(
    config: Config,
    manifest: Manifest,
    dry_run: bool = False,
    limit: int | None = None,
    include_opened: bool = False,
    opener: OpenPath | None = None,
) -> AcsmOpenResult:
    """批次用系統預設程式開啟已下載的 .acsm。"""
    plan = build_plan(manifest, config, include_opened=include_opened)
    if dry_run:
        return AcsmOpenResult(opened=0, dry_run=True, plan=plan)

    open_path = opener or _open_path
    opened = 0
    items = plan.openable[:limit] if limit and limit > 0 else plan.openable
    for item in items:
        open_path(item.path)
        item.book.acsm_opened_at = now_iso()
        manifest.upsert(item.book)
        manifest.save()
        opened += 1
    return AcsmOpenResult(opened=opened, dry_run=False, plan=plan)


def write_report(manifest: Manifest, config: Config) -> Path:
    """輸出 ACSM 交接報表。"""
    plan = build_plan(manifest, config)
    path = config.output_dir / ACSM_REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    add = lines.append
    add("OpenShelf ACSM 交接報表")
    add(f"產生時間：{now_iso()}")
    add("=" * 48)
    add("")
    add("【統計】")
    add(f"  尚未交接 ADE / 系統預設程式：{len(plan.openable)}")
    add(f"  已送出給 ADE / 系統預設程式：{len(plan.already_opened)}")
    add(f"  檔案遺失（manifest 有記錄但檔案不存在）：{len(plan.missing)}")
    add(f"  其他狀態（無 DRM／無法匯出／失敗／待下載）：{len(plan.skipped)}")
    add("")

    add("【尚未交接的 .acsm】")
    if plan.openable:
        for item in plan.openable:
            add(f"  + {_book_label(item.book)}")
            add(f"      {item.path}")
    else:
        add("  （無）")
    add("")

    add("【已送出給 ADE / 系統預設程式】")
    if plan.already_opened:
        for item in plan.already_opened:
            add(f"  = {_book_label(item.book)}")
            if item.book.acsm_opened_at:
                add(f"      送出時間：{item.book.acsm_opened_at}")
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


def _book_label(book: BookEntry) -> str:
    label = book.title or book.volume_id
    if book.author:
        label += f" - {book.author}"
    return label


def _open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    else:
        subprocess.run(["xdg-open", str(path)], check=True)
