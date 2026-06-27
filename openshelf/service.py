"""scan / export 的協調邏輯——CLI 與 GUI 共用的單一實作。

把「枚舉→分類→寫 manifest」與「逐本下載→覆核→續傳」集中於此，
讓 CLI（rich 主控台）與 GUI（Qt 訊號）只需提供 log / progress 回呼，
不必各自複製流程，避免兩邊行為走鐘。

實際的端點存取仍在 playbooks.py；本層不碰任何 DRM 解析。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .classify import classify
from .config import Config
from .export import download_option
from .logsetup import get_logger
from .manifest import BookEntry, Manifest, now_iso
from .playbooks import ExportOption, list_library
from .session import SessionExpired, build_client

# log(訊息)；progress(已處理, 總數)；status(目前書名)；should_stop() -> bool（GUI 取消用）
LogCb = Callable[[str], None]
ProgressCb = Callable[[int, int], None]
StatusCb = Callable[[str], None]
StopCb = Callable[[], bool]


def _noop_log(_msg: str) -> None:
    pass


def _noop_progress(_done: int, _total: int) -> None:
    pass


def _noop_status(_book: str) -> None:
    pass


def _never_stop() -> bool:
    return False


def _tee_log(cfg: Config, log: LogCb | None) -> LogCb:
    """把使用者的 log 回呼與檔案日誌串接：訊息同時顯示與寫入 output/openshelf.log。"""
    user_log = log or _noop_log
    try:
        logger = get_logger(cfg.output_dir)
    except OSError:
        return user_log  # 無法建立日誌檔時，至少不影響主流程

    def _log(msg: str) -> None:
        user_log(msg)
        logger.info(msg)

    return _log


_BOOK_FMTS = ("epub", "pdf")


def _candidates(
    category: str, options: list[ExportOption], prefer_format: str
) -> list[ExportOption]:
    """要嘗試下載的格式，依序回傳；無 DRM 書一個格式失敗可改試另一個。"""
    if category == "drm_free":
        by = {o.fmt.lower(): o for o in options if o.fmt.lower() in _BOOK_FMTS}
        order = ("epub", "pdf") if prefer_format == "epub" else ("pdf", "epub")
        return [by[f] for f in order if f in by]
    if category == "acsm":
        return [o for o in options if o.fmt.lower() == "acsm"]
    return []


def _year(published: str) -> str:
    return (published or "")[:4]


def _disambiguator(entry: BookEntry, group: list[BookEntry]) -> str | None:
    """同名（書名+作者）多本時的檔名辨識：以『出版年 · 出版社』區別；
    年＋出版社仍相同才補 volume_id，確保檔名唯一不互相覆蓋。"""
    if len(group) <= 1:
        return None
    year, pub = _year(entry.published), (entry.publisher or "").strip()
    parts = [p for p in (year, pub) if p]
    key = (year, pub)
    same = sum(
        1 for b in group if (_year(b.published), (b.publisher or "").strip()) == key
    )
    if same > 1:  # 年＋出版社也撞，補 volume_id
        parts.append(entry.volume_id)
    return " · ".join(parts) if parts else entry.volume_id


def _is_stale_acsm(entry: BookEntry, cfg: Config) -> bool:
    """已下載的 .acsm 是否逾「有效天數」（以下載時間為準，不解析 .acsm 內容）。"""
    if entry.category != "acsm" or not entry.downloaded_at:
        return False
    try:
        dt = datetime.fromisoformat(entry.downloaded_at)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - dt).days >= cfg.acsm_valid_days


def count_stale_acsm(manifest: Manifest, cfg: Config) -> int:
    """已下載但逾時、建議重抓的 .acsm 本數。"""
    return sum(
        1
        for b in manifest.books.values()
        if b.file_path and _is_stale_acsm(b, cfg)
    )


REPORT_NAME = "下載報表.txt"


def _book_label(b: BookEntry) -> str:
    name = b.title or b.volume_id
    if b.author:
        name += f" - {b.author}"
    if b.publisher:
        name += f"（{b.publisher}）"
    return name


def write_report(manifest: Manifest, cfg: Config) -> Path:
    """在輸出目錄寫一份人看得懂的下載報表（純文字），重點列出缺漏的書。"""
    books = list(manifest.books.values())
    c = manifest.counts()
    drm_free = [b for b in books if b.category == "drm_free" and b.file_path]
    acsm = [b for b in books if b.category == "acsm" and b.file_path]
    no_export = [b for b in books if b.category == "no_export"]
    failed = [b for b in books if b.category == "failed"]
    stale = [b for b in books if b.file_path and _is_stale_acsm(b, cfg)]

    lines: list[str] = []
    add = lines.append
    add("OpenShelf 下載報表")
    add(f"產生時間：{now_iso()}")
    add("=" * 48)
    add("")
    add("【統計】")
    add(f"  總計：{c.get('total', 0)}")
    add(f"  已下載 無 DRM（EPUB/PDF）：{len(drm_free)}")
    add(f"  可交接 Calibre（無 DRM EPUB/PDF）：{len(drm_free)}")
    add(f"  已下載 DRM（.acsm，需 ADE 開啟）：{len(acsm)}")
    add(f"  無法匯出（只記錄）：{len(no_export)}")
    add(f"  失敗（未取得書檔）：{len(failed)}")
    if stale:
        add(f"  ⚠ .acsm 逾 {cfg.acsm_valid_days} 天（建議重抓）：{len(stale)}")
    add("")

    add("【缺漏 1：失敗，未取得書檔】")
    if failed:
        for b in failed:
            add(f"  ✗ {_book_label(b)}")
            if b.note:
                add(f"      原因：{b.note}")
    else:
        add("  （無）")
    add("")

    add("【缺漏 2：無法匯出（Google 未提供下載，只能在 Play Books App／網頁閱讀）】")
    if no_export:
        for b in no_export:
            add(f"  - {_book_label(b)}")
    else:
        add("  （無）")
    add("")

    if stale:
        add("【.acsm 逾時，建議 openshelf export --refresh-acsm 重抓】")
        for b in stale:
            add(f"  ! {_book_label(b)}")
        add("")

    path = cfg.output_dir / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig：讓 Windows 記事本直接正確顯示中文
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    return path


CSV_NAME = "書庫清單.csv"
HTML_NAME = "書庫報表.html"

_CSV_HEADERS = (
    "書名", "作者", "出版社", "出版日期", "分類",
    "檔案", "下載時間", "備註", "volume_id",
)
_CATEGORY_ZH = {
    "drm_free": "無 DRM（EPUB/PDF）",
    "acsm": "DRM（.acsm，需 ADE）",
    "no_export": "無法匯出（只記錄）",
    "failed": "失敗（未取得書檔）",
    "pending": "待下載",
}


def _row_values(b: BookEntry) -> tuple[str, ...]:
    return (
        b.title or "", b.author or "", b.publisher or "", b.published or "",
        _CATEGORY_ZH.get(b.category, b.category), b.file_path or "",
        b.downloaded_at or "", b.note or "", b.volume_id,
    )


def write_csv(manifest: Manifest, cfg: Config) -> Path:
    """匯出書庫清單為 CSV（utf-8-sig，Excel 可直接開）。"""
    import csv

    books = sorted(manifest.books.values(), key=lambda b: (b.title or "", b.volume_id))
    path = cfg.output_dir / CSV_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_HEADERS)
        for b in books:
            writer.writerow(_row_values(b))
    return path


def write_html(manifest: Manifest, cfg: Config) -> Path:
    """匯出書庫報表為單一 HTML（內嵌 CSS，可離線開啟）。"""
    from html import escape

    c = manifest.counts()
    books = sorted(manifest.books.values(), key=lambda b: (b.category, b.title or ""))
    stale = sum(1 for b in manifest.books.values() if b.file_path and _is_stale_acsm(b, cfg))

    rows = []
    for b in books:
        vals = _row_values(b)
        cells = "".join(f"<td>{escape(str(v))}</td>" for v in vals)
        rows.append(f'<tr class="{escape(b.category)}">{cells}</tr>')

    head = "".join(f"<th>{escape(h)}</th>" for h in _CSV_HEADERS)
    stats = (
        f"總計 {c.get('total', 0)}｜無 DRM {c.get('drm_free', 0)}｜"
        f"ACSM {c.get('acsm', 0)}｜無法匯出 {c.get('no_export', 0)}｜"
        f"失敗 {c.get('failed', 0)}"
    )
    if stale:
        stats += f"｜⚠ .acsm 逾時 {stale}"

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenShelf 書庫報表</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif;
         margin: 24px; color: #1f2330; }}
  h1 {{ font-size: 20px; }}
  .stats {{ color: #444; margin: 8px 0 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
  th, td {{ border: 1px solid #e0e3ea; padding: 6px 8px; text-align: left;
            vertical-align: top; }}
  th {{ background: #2d5bff; color: #fff; position: sticky; top: 0; }}
  tr:nth-child(even) td {{ background: #f6f8fc; }}
  tr.failed td {{ background: #fdecec; }}
  tr.no_export td {{ color: #888; }}
  .foot {{ color: #888; margin-top: 16px; font-size: 12px; }}
</style>
</head>
<body>
<h1>📚 OpenShelf 書庫報表</h1>
<div class="stats">{escape(stats)}　·　產生時間 {escape(now_iso())}</div>
<table>
  <thead><tr>{head}</tr></thead>
  <tbody>
    {"".join(rows)}
  </tbody>
</table>
<div class="foot">僅供匯出你自己合法擁有的電子書；不解析 ACSM、不抽金鑰、不移除任何保護。</div>
</body>
</html>
"""
    path = cfg.output_dir / HTML_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")
    return path


@dataclass
class ScanResult:
    manifest: Manifest
    option_cache: dict[str, list[ExportOption]] = field(default_factory=dict)


@dataclass
class ExportResult:
    done: int = 0
    skipped: int = 0
    failed: int = 0


def scan(cfg: Config, log: LogCb | None = None) -> ScanResult:
    """枚舉書庫、分類並寫入 manifest。回傳 manifest 與本次取得的匯出選項快取。"""
    log = _tee_log(cfg, log)
    manifest = Manifest.load(cfg.manifest_path)
    option_cache: dict[str, list[ExportOption]] = {}

    client = build_client(cfg)
    with client:
        books = list_library(client)
        for lb in books:
            options = lb.export_options
            category = classify(options)
            entry = manifest.get(lb.volume_id) or BookEntry(volume_id=lb.volume_id)
            entry.title = lb.title or entry.title
            entry.author = lb.author or entry.author
            entry.publisher = lb.publisher or entry.publisher
            entry.published = lb.published or entry.published
            entry.cover_url = lb.cover_url or entry.cover_url
            # 已成功下載者不要被重新分類降級
            if entry.category not in {"drm_free", "acsm"} or not entry.file_path:
                entry.category = category
            manifest.upsert(entry)
            option_cache[lb.volume_id] = options
            log(f"枚舉：{entry.title or lb.volume_id} → {category}")

    manifest.save()
    log(f"報表已寫入：{write_report(manifest, cfg)}")
    return ScanResult(manifest=manifest, option_cache=option_cache)


def export(
    cfg: Config,
    prefer_format: str,
    include_acsm: bool,
    option_cache: dict[str, list[ExportOption]] | None = None,
    log: LogCb | None = None,
    progress: ProgressCb | None = None,
    status: StatusCb | None = None,
    should_stop: StopCb | None = None,
    limit: int | None = None,
    only: str | None = None,
    refresh_acsm: bool = False,
    skip_failed: bool = False,
    only_failed: bool = False,
) -> ExportResult:
    """逐本下載可匯出的書。回傳下載 / 跳過 / 失敗計數。

    limit：最多嘗試下載幾本（測試用）。only：只下載某一分類（drm_free / acsm）。
    refresh_acsm：重抓已逾「有效天數」的 .acsm（以下載時間為準）。
    skip_failed：略過 manifest 中已標記 failed 的書，不再重試（如 Google 端不給檔者）。
    """
    log = _tee_log(cfg, log)
    progress = progress or _noop_progress
    status = status or _noop_status
    should_stop = should_stop or _never_stop
    option_cache = option_cache or {}

    manifest = Manifest.load(cfg.manifest_path)
    result = ExportResult()
    targets = list(manifest.books.items())
    total = len(targets)
    attempted = 0

    # 同名（書名+作者）分組，供「年 · 出版社」辨識；仍相同才補 volume_id
    groups: dict[tuple[str, str], list[BookEntry]] = defaultdict(list)
    for b in manifest.books.values():
        groups[(b.title, b.author)].append(b)

    client = build_client(cfg)
    with client:
        # 下載 URL 在書庫枚舉時一併取得；沒有現成快取就枚舉一次補上
        if not option_cache:
            option_cache = {b.volume_id: b.export_options for b in list_library(client)}

        for index, (vid, entry) in enumerate(targets, start=1):
            progress(index, total)
            if should_stop():
                log("已取消。")
                break
            if skip_failed and entry.category == "failed":
                continue
            if only_failed and entry.category != "failed":
                continue

            # 以「當前選項」即時判定分類，讓先前 failed 的書下次也會被重試
            options = option_cache.get(vid) or []
            eff = classify(options)
            if eff == "no_export":
                continue
            if only and eff != only:
                continue
            if eff == "acsm" and not include_acsm:
                continue
            if manifest.is_downloaded(vid, cfg.output_dir):
                # 已下載；逾時的 .acsm 在 refresh_acsm 時重抓，其餘跳過
                if refresh_acsm and eff == "acsm" and _is_stale_acsm(entry, cfg):
                    log(f"↻ 逾時重抓：{entry.title or vid}")
                else:
                    result.skipped += 1
                    continue

            candidates = _candidates(eff, options, prefer_format)
            if not candidates:
                continue

            disambiguator = _disambiguator(entry, groups[(entry.title, entry.author)])
            attempted += 1
            status(entry.title or vid)
            filename: str | None = None
            last_error: Exception | None = None
            for opt in candidates:  # 無 DRM 書某格式失敗時，改試另一格式
                try:
                    filename = download_option(
                        client,
                        opt,
                        cfg.output_dir,
                        entry.title,
                        entry.author,
                        retries=cfg.download_retries,
                        disambiguator=disambiguator,
                    )
                    break
                except SessionExpired:
                    raise  # 登入態失效：中止整批，交由上層提示重新登入
                except Exception as e:  # noqa: BLE001 — 試下一個格式
                    last_error = e

            if filename:
                entry.category = eff
                entry.file_path = filename
                entry.downloaded_at = now_iso()
                entry.note = ""
                manifest.upsert(entry)
                manifest.save()
                result.done += 1
                log(f"OK {filename}")
            else:
                note = f"{type(last_error).__name__}: {last_error}"
                # 重抓既有檔失敗時，舊檔還在 → 保留原分類，只記錄
                if entry.file_path and (cfg.output_dir / entry.file_path).exists():
                    entry.note = f"refresh failed: {note}"
                else:
                    entry.category = "failed"
                    entry.note = note
                manifest.upsert(entry)
                manifest.save()
                result.failed += 1
                log(f"FAIL {entry.title or vid}: {last_error}")

            if limit and attempted >= limit:
                break
            time.sleep(cfg.throttle_seconds)

    log(f"報表已寫入：{write_report(manifest, cfg)}")
    return result
