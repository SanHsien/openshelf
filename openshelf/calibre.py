"""Calibre 交接：匯入已下載的無 DRM EPUB/PDF。

本模組只處理 manifest 中分類為 drm_free、且檔案存在的 EPUB/PDF。
不處理 .acsm，不安裝或設定任何外掛，也不移除任何保護。
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .manifest import BookEntry, Manifest, now_iso

RunCmd = Callable[[list[str]], subprocess.CompletedProcess]

CALIBRE_REPORT_NAME = "Calibre交接報表.txt"
_COMMON_CALIBREDB = (
    Path(r"C:\Program Files\Calibre2\calibredb.exe"),
    Path(r"C:\Program Files (x86)\Calibre2\calibredb.exe"),
)
_BATCH_SIZE = 80


class CalibreNotFound(RuntimeError):
    """找不到 Calibre CLI。"""


@dataclass
class CalibreItem:
    book: BookEntry
    path: Path


@dataclass
class CalibrePlan:
    importable: list[CalibreItem] = field(default_factory=list)
    missing: list[BookEntry] = field(default_factory=list)
    acsm: list[BookEntry] = field(default_factory=list)
    skipped: list[BookEntry] = field(default_factory=list)


@dataclass
class CalibreImportResult:
    imported: int = 0
    dry_run: bool = False
    report_path: Path | None = None
    plan: CalibrePlan = field(default_factory=CalibrePlan)


def find_calibredb(config: Config) -> Path:
    """找出 calibredb.exe。"""
    if config.calibredb_path:
        path = config.calibredb_path
        if path.is_file():
            return path
        raise CalibreNotFound(f"找不到 calibredb：{path}")

    found = shutil.which("calibredb")
    if found:
        return Path(found)

    for path in _COMMON_CALIBREDB:
        if path.is_file():
            return path

    raise CalibreNotFound(
        "找不到 Calibre CLI。請安裝 Calibre 64-bit，或在 config.toml 設定 "
        r'calibredb_path = "C:\Program Files\Calibre2\calibredb.exe"。'
    )


def build_plan(manifest: Manifest, config: Config) -> CalibrePlan:
    """依 manifest 建立 Calibre 交接計畫。"""
    plan = CalibrePlan()
    for book in manifest.books.values():
        if book.category == "drm_free" and book.file_path:
            path = config.output_dir / book.file_path
            if path.is_file():
                plan.importable.append(CalibreItem(book=book, path=path))
            else:
                plan.missing.append(book)
        elif book.category == "acsm":
            plan.acsm.append(book)
        else:
            plan.skipped.append(book)
    return plan


def import_drm_free(
    config: Config,
    manifest: Manifest,
    library_path: Path | None = None,
    dry_run: bool = False,
    run_cmd: RunCmd | None = None,
) -> CalibreImportResult:
    """把已下載的無 DRM EPUB/PDF 匯入 Calibre。"""
    plan = build_plan(manifest, config)
    if dry_run or not plan.importable:
        return CalibreImportResult(imported=0, dry_run=dry_run, plan=plan)

    calibredb = find_calibredb(config)
    runner = run_cmd or _run
    imported = 0
    for batch in _chunks(plan.importable, _BATCH_SIZE):
        cmd = [str(calibredb), "add"]
        target_library = library_path or config.calibre_library
        if target_library:
            cmd += ["--library-path", str(target_library)]
        cmd += [str(item.path) for item in batch]
        runner(cmd)
        imported += len(batch)

    return CalibreImportResult(imported=imported, dry_run=False, plan=plan)


def write_report(manifest: Manifest, config: Config) -> Path:
    """輸出 Calibre 交接報表。"""
    plan = build_plan(manifest, config)
    path = config.output_dir / CALIBRE_REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    add = lines.append
    add("OpenShelf Calibre 交接報表")
    add(f"產生時間：{now_iso()}")
    add("=" * 48)
    add("")
    add("【統計】")
    add(f"  可匯入 Calibre（無 DRM EPUB/PDF）：{len(plan.importable)}")
    add(f"  檔案遺失（manifest 有記錄但檔案不存在）：{len(plan.missing)}")
    add(f"  不匯入 Calibre（.acsm，需 ADE 開啟）：{len(plan.acsm)}")
    add(f"  其他狀態（無法匯出／失敗／待下載）：{len(plan.skipped)}")
    add("")

    add("【可匯入 Calibre】")
    if plan.importable:
        for item in plan.importable:
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

    add("【.acsm 不匯入 Calibre】")
    if plan.acsm:
        for book in plan.acsm:
            add(f"  - {_book_label(book)}")
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


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True)


def _chunks(items: list[CalibreItem], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]
