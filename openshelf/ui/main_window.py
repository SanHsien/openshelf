"""OpenShelf 桌面圖形介面（PySide6）。

M6 殼：把 service.scan / service.export 接到視窗按鈕，於背景執行緒跑、
以訊號回報 log 與進度，並用表格呈現 manifest。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import __version__, acsm, browser, calibre, reader, service, update
from ..config import Config
from ..manifest import Manifest
from ..playbooks import cover_thumb_url
from .i18n import LANGUAGES, current_language, detect_default, set_language, tr

_COVER_SIZE = (36, 48)  # 縮圖顯示尺寸（寬, 高）

GITHUB_URL = "https://github.com/SanHsien/openshelf"
AUTHOR = "SanHsien"
LICENSE_NAME = "Apache License 2.0"

try:
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtCore import Qt, QSettings, QSize, QThread, QTimer, QUrl, Signal
    from PySide6.QtNetwork import (
        QNetworkAccessManager,
        QNetworkReply,
        QNetworkRequest,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError as e:  # 讓 `import` 失敗時 cli.py 能給出安裝指引
    raise ImportError("需要 PySide6：pip install -e '.[gui]'") from e


# 分類在表格中的顯示字串（繁中原字串，經 tr() 轉譯）
_CATEGORY_SRC = {
    "drm_free": "無 DRM（EPUB/PDF）",
    "acsm": "DRM（.acsm，需 ADE）",
    "no_export": "無法匯出",
    "failed": "失敗",
    "pending": "待下載",
}

# 表頭（繁中原字串）
_HEADERS = ("書名", "作者", "出版社", "分類", "檔案", "ID")


def category_label(cat: str) -> str:
    return tr(_CATEGORY_SRC.get(cat, cat))

# 每欄的初始寬度，也是 reload 自動符合內容時的上限。書名（0）改為可手動拖曳、
# 雙擊欄界自動符合內容（不再用 Stretch，否則無法調整、橫向卷軸也會消失）。
_TABLE_WIDTHS = {
    0: 360,  # 書名
    1: 180,  # 作者
    2: 160,  # 出版社
    3: 140,  # 分類
    4: 260,  # 檔案
    5: 180,  # ID
}

# 自動符合內容時的寬度下限，避免書庫為空或內容很短時欄位塌縮成一小條。
_MIN_WIDTHS = {
    0: 240,  # 書名
    1: 110,
    2: 100,
    3: 90,
    4: 150,
    5: 110,
}


def _asset(name: str) -> Path:
    """資產路徑：開發時取專案根 assets/，frozen 時取 sys._MEIPASS/assets/。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "assets" / name


def app_icon() -> QIcon:
    """載入視窗／工作列 icon；找不到檔案時回傳空 QIcon（不致命）。"""
    for name in ("openshelf.png", "openshelf.ico"):
        p = _asset(name)
        if p.is_file():
            return QIcon(str(p))
    return QIcon()

_FILTERS = (
    ("全部", "all"),
    ("無 DRM", "drm_free"),
    ("ACSM", "acsm"),
    ("無法匯出", "no_export"),
    ("失敗", "failed"),
    ("待下載", "pending"),
)


class Worker(QThread):
    """在背景執行緒跑一個函式；函式收到 worker 本身以回報 log/progress 與查詢是否取消。"""

    log = Signal(str)
    progress = Signal(int, int)
    status = Signal(str)
    need_confirm = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self._stop = False
        self._confirm_event = threading.Event()

    # 供函式呼叫 ----------------------------------------------------
    def should_stop(self) -> bool:
        return self._stop

    def wait_confirm(self, message: str = "") -> None:
        """阻塞背景執行緒，直到主執行緒回應 confirm()。"""
        self._confirm_event.clear()
        self.need_confirm.emit(message)
        self._confirm_event.wait()

    # 供主執行緒呼叫 ------------------------------------------------
    def stop(self) -> None:
        self._stop = True

    def confirm(self) -> None:
        self._confirm_event.set()

    def run(self) -> None:
        try:
            self.done.emit(self._fn(self))
        except Exception as e:  # noqa: BLE001 — 回報給 UI，不讓執行緒崩潰
            self.failed.emit(f"{type(e).__name__}: {e}")


class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self.cfg = config
        self._worker: Worker | None = None

        self.setWindowTitle(tr("OpenShelf"))
        self.setWindowIcon(app_icon())
        self.resize(900, 600)

        # 工具列按鈕
        self.btn_login = QPushButton(tr("登入"))
        self.btn_scan = QPushButton(tr("掃描書庫"))
        self.btn_export = QPushButton(tr("下載"))
        self.btn_retry = QPushButton(tr("重試失敗"))
        self.btn_retry.setToolTip(tr("只重新嘗試先前標記為失敗的書"))
        self.btn_stop = QPushButton(tr("停止"))
        self.btn_update = QPushButton(tr("檢查更新"))
        self.btn_about = QPushButton(tr("ℹ 關於"))
        self.btn_about.setToolTip(tr("關於 OpenShelf（版本、作者、GitHub）"))
        self.btn_calibre_preview = QPushButton(tr("檢查EPUB/PDF"))
        self.btn_calibre_import = QPushButton(tr("交接EPUB/PDF"))
        self.btn_calibre_report = QPushButton(tr("EPUB/PDF報表"))
        self.btn_acsm_preview = QPushButton(tr("檢查ACSM"))
        self.btn_acsm_open = QPushButton(tr("開啟ACSM"))
        self.btn_acsm_report = QPushButton(tr("ACSM報表"))
        self.acsm_batch = QSpinBox()
        self.acsm_batch.setRange(1, 999)
        self.acsm_batch.setValue(25)
        self.acsm_batch.setToolTip(
            tr("一次送給 ADE 的 .acsm 數量；建議分批處理，避免憑證排隊過期")
        )
        self.btn_refresh = QPushButton(tr("重新整理"))
        self.btn_report = QPushButton(tr("匯出CSV/HTML"))
        self.btn_report.setToolTip(tr("把書庫清單匯出為 CSV 與 HTML 報表並開啟資料夾"))
        self.btn_stop.setEnabled(False)

        self.fmt = QComboBox()
        self.fmt.addItems(["epub", "pdf"])
        self.fmt.setCurrentText(config.prefer_format)
        self.chk_acsm = QCheckBox(tr("抓 .acsm"))
        self.chk_acsm.setChecked(config.include_acsm)
        self.chk_refresh = QCheckBox(tr("重抓逾時 .acsm"))
        self.chk_force_refresh = QCheckBox(tr("強制重抓 .acsm"))
        self.chk_force_refresh.setToolTip(
            tr("ADE 顯示 E_ADEPT_REQUEST_EXPIRED 時使用：不看有效天數，重新下載官方 .acsm 憑證")
        )
        self.chk_include_opened_acsm = QCheckBox(tr("包含已送出"))
        self.chk_include_opened_acsm.setToolTip(
            tr("ADE 當場失敗時使用：重新送出先前已交接的 .acsm")
        )
        self.chk_skipfail = QCheckBox(tr("略過已知失敗"))
        self.filter_combo = QComboBox()
        for label, value in _FILTERS:
            self.filter_combo.addItem(tr(label), value)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("搜尋 書名／作者／出版社"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.chk_cover = QCheckBox(tr("顯示封面"))
        self.chk_cover.setToolTip(
            tr("顯示書籍封面縮圖（需連網抓封面圖片，會快取於 output/.cover_cache）")
        )
        self.ebook_target = QComboBox()
        self.ebook_target.addItem("Calibre", "calibre")
        self.ebook_target.addItem("ADE", "ade")
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(LANGUAGES.index(current_language()))

        # 摘要標籤（前綴經 tr()，數字在 _update_summary 補上）
        self.summary_labels = {
            key: QLabel() for key in
            ("total", "drm_free", "acsm", "no_export", "failed", "calibre")
        }

        # 需在切換語言時重新轉譯的內嵌標籤
        self.lbl_drmfmt = QLabel(tr("無 DRM 格式"))
        self.lbl_target = QLabel(tr("目標"))
        self.lbl_acsm_batch = QLabel(tr("批次"))
        self.lbl_search = QLabel(tr("搜尋"))
        self.lbl_filter = QLabel(tr("篩選"))
        self.lbl_lang = QLabel(tr("語言"))
        self.lbl_log = QLabel(tr("紀錄"))

        self.library_group = QGroupBox(tr("書庫"))
        library_group = self.library_group
        library_bar = QHBoxLayout()
        for w in (
            self.btn_login,
            self.btn_scan,
            self.btn_refresh,
            self.btn_report,
            self.btn_stop,
        ):
            library_bar.addWidget(w)
        library_bar.addStretch(1)
        library_bar.addWidget(self.btn_update)
        library_bar.addWidget(self.btn_about)
        library_group.setLayout(library_bar)

        self.download_group = QGroupBox(tr("下載"))
        download_group = self.download_group
        download_bar = QHBoxLayout()
        download_bar.addWidget(self.btn_export)
        download_bar.addWidget(self.btn_retry)
        download_bar.addWidget(self.lbl_drmfmt)
        download_bar.addWidget(self.fmt)
        download_bar.addWidget(self.chk_acsm)
        download_bar.addWidget(self.chk_refresh)
        download_bar.addWidget(self.chk_force_refresh)
        download_bar.addWidget(self.chk_skipfail)
        download_bar.addStretch(1)
        download_group.setLayout(download_bar)

        acsm_tab = QWidget()
        acsm_bar = QHBoxLayout()
        acsm_bar.addWidget(self.lbl_acsm_batch)
        acsm_bar.addWidget(self.acsm_batch)
        acsm_bar.addWidget(self.chk_include_opened_acsm)
        for w in (self.btn_acsm_preview, self.btn_acsm_open, self.btn_acsm_report):
            acsm_bar.addWidget(w)
        acsm_bar.addStretch(1)
        acsm_tab.setLayout(acsm_bar)

        calibre_tab = QWidget()
        calibre_bar = QHBoxLayout()
        calibre_bar.addWidget(self.lbl_target)
        calibre_bar.addWidget(self.ebook_target)
        for w in (
            self.btn_calibre_preview,
            self.btn_calibre_import,
            self.btn_calibre_report,
        ):
            calibre_bar.addWidget(w)
        calibre_bar.addStretch(1)
        calibre_tab.setLayout(calibre_bar)

        self.handoff_tabs = QTabWidget()
        handoff_tabs = self.handoff_tabs
        handoff_tabs.addTab(acsm_tab, tr("ACSM"))
        handoff_tabs.addTab(calibre_tab, tr("EPUB/PDF"))

        control_row = QHBoxLayout()
        control_row.addWidget(library_group, stretch=2)
        control_row.addWidget(download_group, stretch=3)

        summary_row = QHBoxLayout()
        for label in self.summary_labels.values():
            summary_row.addWidget(label)
        summary_row.addStretch(1)
        summary_row.addWidget(self.chk_cover)
        summary_row.addWidget(self.lbl_search)
        summary_row.addWidget(self.search)
        summary_row.addWidget(self.lbl_filter)
        summary_row.addWidget(self.filter_combo)
        summary_row.addWidget(self.lbl_lang)
        summary_row.addWidget(self.lang_combo)

        # 書目表格
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr(h) for h in _HEADERS])
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        # 全欄皆 Interactive：可手動拖曳、雙擊欄界自動符合內容；不固定最後一欄。
        header.setStretchLastSection(False)
        for col, width in _TABLE_WIDTHS.items():
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, width)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)

        # 記住欄寬／排序：啟動時還原使用者上次的表頭狀態
        self._settings = QSettings("OpenShelf", "OpenShelf")
        self._header_restored = False
        saved = self._settings.value("table/header_state")
        if saved is not None and self.table.horizontalHeader().restoreState(saved):
            self._header_restored = True
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_: self._save_header_state()
        )

        # 封面縮圖：非同步抓取 + 快取（只在勾選「顯示封面」時啟用）
        self._nam = QNetworkAccessManager(self)
        self._cover_pixmaps: dict[str, QPixmap] = {}
        self._title_items: dict[str, QTableWidgetItem] = {}
        self._cover_pending: set[str] = set()

        # 進度條（下載時顯示已處理 / 總數）+ 目前書名與預計剩餘時間
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.queue_label = QLabel()
        self.queue_label.setVisible(False)
        self._dl_start = 0.0
        self._cur_book = ""

        # log 區
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setMaximumBlockCount(2000)

        layout = QVBoxLayout()
        layout.addLayout(control_row)
        layout.addWidget(handoff_tabs)
        layout.addLayout(summary_row)
        layout.addWidget(self.table, stretch=3)
        layout.addWidget(self.progress)
        layout.addWidget(self.queue_label)
        layout.addWidget(self.lbl_log)
        layout.addWidget(self.logview, stretch=1)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)
        self.counts_label = QLabel()
        self.statusBar().addPermanentWidget(self.counts_label)

        # 連線
        self.btn_login.clicked.connect(self.on_login)
        self.btn_scan.clicked.connect(self.on_scan)
        self.btn_export.clicked.connect(self.on_export)
        self.btn_retry.clicked.connect(self.on_retry_failed)
        self.btn_calibre_preview.clicked.connect(self.on_calibre_preview)
        self.btn_calibre_import.clicked.connect(self.on_calibre_import)
        self.btn_calibre_report.clicked.connect(self.on_calibre_report)
        self.btn_acsm_preview.clicked.connect(self.on_acsm_preview)
        self.btn_acsm_open.clicked.connect(self.on_acsm_open)
        self.btn_acsm_report.clicked.connect(self.on_acsm_report)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_refresh.clicked.connect(self.reload_manifest)
        self.btn_report.clicked.connect(self.on_export_report)
        self.btn_update.clicked.connect(lambda: self.on_check_update(manual=True))
        self.btn_about.clicked.connect(self.on_about)
        self.filter_combo.currentIndexChanged.connect(self.reload_manifest)
        self.search.textChanged.connect(self.reload_manifest)
        self.chk_cover.toggled.connect(self.reload_manifest)
        self.lang_combo.currentIndexChanged.connect(self.on_lang_change)

        self.reload_manifest()
        # 啟動時靜默檢查更新（失敗或最新版皆不打擾，只有更新時提示）
        self.on_check_update(manual=False)
        # 首次啟動導覽：等事件迴圈起來再彈，避免阻塞建構（測試不跑迴圈即不觸發）
        QTimer.singleShot(0, self._maybe_onboard)

    # ---- manifest 呈現 ------------------------------------------
    def reload_manifest(self) -> None:
        manifest = Manifest.load(self.cfg.manifest_path)
        all_books = list(manifest.books.values())
        selected = self.filter_combo.currentData()
        books = [
            b for b in all_books if selected in (None, "all") or b.category == selected
        ]
        query = self.search.text().strip().lower()
        if query:
            books = [
                b
                for b in books
                if query in (b.title or "").lower()
                or query in (b.author or "").lower()
                or query in (b.publisher or "").lower()
            ]
        sort_col = self.table.horizontalHeader().sortIndicatorSection()
        sort_order = self.table.horizontalHeader().sortIndicatorOrder()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(books))
        self._title_items = {}
        covers_on = self.chk_cover.isChecked()
        self.table.setIconSize(QSize(*_COVER_SIZE) if covers_on else QSize(0, 0))
        for row, b in enumerate(books):
            cells = [
                b.title,
                b.author,
                b.publisher,
                category_label(b.category),
                b.file_path or "",
                b.volume_id,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                item.setToolTip(str(text))
                self.table.setItem(row, col, item)
                if col == 0:
                    self._title_items[b.volume_id] = item
            if covers_on:
                self._load_cover(b)
        # 只在沒有還原過使用者欄寬時自動符合一次，之後沿用記住的欄寬
        if not self._header_restored:
            self._fit_table_columns()
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(sort_col, sort_order)
        c = manifest.counts()
        text = (
            f"{tr('總計')} {c.get('total', 0)}｜{tr('無 DRM')} {c.get('drm_free', 0)}｜"
            f"{tr('ACSM')} {c.get('acsm', 0)}｜{tr('無法匯出')} {c.get('no_export', 0)}｜"
            f"{tr('失敗')} {c.get('failed', 0)}"
        )
        stale = service.count_stale_acsm(manifest, self.cfg)
        if stale:
            text += f"｜⚠ {tr('ACSM')} {stale}"
        self.counts_label.setText(text)
        self._update_summary(manifest)
        self._update_action_state(manifest)

    def _fit_table_columns(self) -> None:
        header = self.table.horizontalHeader()
        for col, max_width in _TABLE_WIDTHS.items():
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            self.table.resizeColumnToContents(col)
            fitted = min(self.table.columnWidth(col), max_width)
            width = max(_MIN_WIDTHS.get(col, 90), fitted)
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, width)

    # ---- 封面縮圖 -----------------------------------------------
    def _cover_cache_path(self, volume_id: str) -> Path:
        key = hashlib.md5(volume_id.encode("utf-8")).hexdigest()
        return self.cfg.output_dir / ".cover_cache" / f"{key}.img"

    def _apply_cover_icon(self, volume_id: str) -> None:
        pix = self._cover_pixmaps.get(volume_id)
        item = self._title_items.get(volume_id)
        if pix is not None and item is not None:
            item.setIcon(QIcon(pix))

    def _load_cover(self, book) -> None:
        """為單本書載入封面：記憶體 → 磁碟快取 → 連網抓取（皆失敗則無圖示）。"""
        vid = book.volume_id
        if vid in self._cover_pixmaps:
            self._apply_cover_icon(vid)
            return
        cache = self._cover_cache_path(vid)
        if cache.is_file():
            pix = QPixmap()
            if pix.load(str(cache)) and not pix.isNull():
                self._cover_pixmaps[vid] = pix.scaledToHeight(
                    _COVER_SIZE[1], Qt.SmoothTransformation
                )
                self._apply_cover_icon(vid)
                return
        if vid in self._cover_pending:
            return
        url = book.cover_url or cover_thumb_url(vid)
        if not url:
            return
        self._cover_pending.add(vid)
        reply = self._nam.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda r=reply, v=vid: self._on_cover_reply(r, v))

    def _on_cover_reply(self, reply, volume_id: str) -> None:
        self._cover_pending.discard(volume_id)
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                data = bytes(reply.readAll())
                pix = QPixmap()
                if data and pix.loadFromData(data) and not pix.isNull():
                    cache = self._cover_cache_path(volume_id)
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_bytes(data)
                    self._cover_pixmaps[volume_id] = pix.scaledToHeight(
                        _COVER_SIZE[1], Qt.SmoothTransformation
                    )
                    self._apply_cover_icon(volume_id)
        finally:
            reply.deleteLater()

    def _save_header_state(self) -> None:
        """把目前欄寬／排序存進設定，並標記為已記住（之後 reload 不再自動符合）。"""
        if getattr(self, "_settings", None) is None:
            return
        self._settings.setValue(
            "table/header_state", self.table.horizontalHeader().saveState()
        )
        self._header_restored = True

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt 介面命名
        self._save_header_state()
        super().closeEvent(event)

    def _update_summary(self, manifest: Manifest) -> None:
        c = manifest.counts()
        calibre_ready = sum(
            1
            for b in manifest.books.values()
            if b.category == "drm_free"
            and b.file_path
            and (self.cfg.output_dir / b.file_path).is_file()
        )
        self.summary_labels["total"].setText(f"{tr('總計')} {c.get('total', 0)}")
        self.summary_labels["drm_free"].setText(f"{tr('無 DRM')} {c.get('drm_free', 0)}")
        self.summary_labels["acsm"].setText(f"{tr('ACSM')} {c.get('acsm', 0)}")
        self.summary_labels["no_export"].setText(f"{tr('無法匯出')} {c.get('no_export', 0)}")
        self.summary_labels["failed"].setText(f"{tr('失敗')} {c.get('failed', 0)}")
        self.summary_labels["calibre"].setText(f"{tr('Calibre')} {calibre_ready}")

    def _update_action_state(self, manifest: Manifest) -> None:
        has_manifest = bool(manifest.books)
        has_acsm = any(
            b.category == "acsm"
            and b.file_path
            and (self.cfg.output_dir / b.file_path).is_file()
            for b in manifest.books.values()
        )
        has_drm_free = any(
            b.category == "drm_free"
            and b.file_path
            and (self.cfg.output_dir / b.file_path).is_file()
            for b in manifest.books.values()
        )
        has_failed = any(b.category == "failed" for b in manifest.books.values())
        self.btn_export.setEnabled(has_manifest)
        self.btn_retry.setEnabled(has_failed)
        self.btn_report.setEnabled(has_manifest)
        self.btn_acsm_preview.setEnabled(has_manifest)
        self.btn_acsm_open.setEnabled(has_acsm)
        self.btn_acsm_report.setEnabled(has_manifest)
        self.btn_calibre_preview.setEnabled(has_manifest)
        self.btn_calibre_import.setEnabled(has_drm_free)
        self.btn_calibre_report.setEnabled(has_manifest)

    # ---- 執行緒協調 ---------------------------------------------
    def _busy(self, busy: bool) -> None:
        for w in (
            self.btn_login,
            self.btn_scan,
            self.btn_export,
            self.btn_retry,
            self.btn_report,
            self.btn_calibre_preview,
            self.btn_calibre_import,
            self.btn_calibre_report,
            self.btn_acsm_preview,
            self.btn_acsm_open,
            self.btn_acsm_report,
            self.btn_refresh,
        ):
            w.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)

    def _run(self, fn, title: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.append_log(f"——{title}——")
        worker = Worker(fn)
        self._worker = worker
        worker.log.connect(self.append_log)
        worker.progress.connect(self._on_progress)
        worker.status.connect(self._on_status)
        worker.need_confirm.connect(self.on_need_confirm)
        worker.done.connect(lambda r: self._on_done(title, r))
        worker.failed.connect(lambda m: self._on_failed(title, m))
        self.progress.setVisible(False)
        self.progress.reset()
        self._dl_start = time.monotonic()
        self._cur_book = ""
        self.queue_label.setVisible(False)
        self._busy(True)
        worker.start()

    @staticmethod
    def _fmt_eta(seconds: float) -> str:
        s = max(0, int(seconds))
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setVisible(True)
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self._update_queue_label(done, total)

    def _on_status(self, book: str) -> None:
        self._cur_book = book
        self._update_queue_label(self.progress.value(), self.progress.maximum())

    def _update_queue_label(self, done: int, total: int) -> None:
        parts = [f"{tr('處理中')} {done}/{total}"]
        if self._cur_book:
            parts.append(f"{tr('目前')}：{self._cur_book}")
        elapsed = time.monotonic() - self._dl_start
        if done > 1 and elapsed > 1:
            remaining = (elapsed / done) * (total - done)
            parts.append(f"{tr('預計剩餘')} ~{self._fmt_eta(remaining)}")
        self.queue_label.setText("　·　".join(parts))
        self.queue_label.setVisible(True)

    def _on_done(self, title: str, result) -> None:
        self._busy(False)
        self.progress.setVisible(False)
        self.queue_label.setVisible(False)
        self.reload_manifest()
        self.append_log(f"{title}完成。")
        if hasattr(result, "done"):
            self.append_log(
                f"下載 {result.done}、跳過 {result.skipped}、失敗 {result.failed}"
            )
        if hasattr(result, "imported"):
            self.append_log(f"匯入 Calibre：{result.imported} 本")
        if hasattr(result, "opened"):
            self.append_log(f"送出檔案：{result.opened} 本")

    def _on_failed(self, title: str, message: str) -> None:
        self._busy(False)
        self.progress.setVisible(False)
        self.queue_label.setVisible(False)
        self.reload_manifest()
        self.append_log(f"[{title}失敗] {message}")
        QMessageBox.warning(self, f"{title}失敗", message)

    def append_log(self, text: str) -> None:
        self.logview.appendPlainText(text)

    # ---- 動作 ---------------------------------------------------
    def on_need_confirm(self, _message: str) -> None:
        QMessageBox.information(
            self,
            "完成登入",
            "請在開啟的瀏覽器完成 Google 登入並看到自己的書庫後，按「OK」繼續。",
        )
        if self._worker is not None:
            self._worker.confirm()

    def on_login(self) -> None:
        cfg = self.cfg
        self._run(lambda w: browser.login(cfg, confirm=w.wait_confirm), "登入")

    def on_scan(self) -> None:
        cfg = self.cfg
        self._run(lambda w: service.scan(cfg, log=w.log.emit), "掃描")

    def on_export(self) -> None:
        cfg = self.cfg
        prefer = self.fmt.currentText()
        include_acsm = self.chk_acsm.isChecked()
        refresh_acsm = self.chk_refresh.isChecked()
        force_refresh_acsm = self.chk_force_refresh.isChecked()
        skip_failed = self.chk_skipfail.isChecked()
        limit = self.acsm_batch.value() if force_refresh_acsm else None
        self._run(
            lambda w: service.export(
                cfg,
                prefer,
                include_acsm,
                log=w.log.emit,
                progress=w.progress.emit,
                status=w.status.emit,
                should_stop=w.should_stop,
                limit=limit,
                refresh_acsm=refresh_acsm,
                force_refresh_acsm=force_refresh_acsm,
                skip_failed=skip_failed,
            ),
            "下載",
        )

    def on_retry_failed(self) -> None:
        cfg = self.cfg
        prefer = self.fmt.currentText()
        include_acsm = self.chk_acsm.isChecked()
        self._run(
            lambda w: service.export(
                cfg,
                prefer,
                include_acsm,
                log=w.log.emit,
                progress=w.progress.emit,
                status=w.status.emit,
                should_stop=w.should_stop,
                only_failed=True,
            ),
            "重試失敗",
        )

    def on_calibre_preview(self) -> None:
        cfg = self.cfg
        target = self.ebook_target.currentData()

        def task(w):
            manifest = Manifest.load(cfg.manifest_path)
            if not manifest.books:
                raise RuntimeError("manifest 為空，請先掃描書庫。")
            if target == "calibre":
                result = calibre.import_drm_free(cfg, manifest, dry_run=True)
                path = calibre.write_report(manifest, cfg)
            else:
                result = reader.open_drm_free(cfg, manifest, target="ade", dry_run=True)
                path = reader.write_report(manifest, cfg, target="ade")
            plan = result.plan
            w.log.emit(
                f"可交接 {len(_plan_ready(plan))} 本、檔案遺失 {len(plan.missing)} 本。"
            )
            w.log.emit(f"EPUB/PDF 交接報表：{path}")
            return result

        self._run(task, "檢查 EPUB/PDF")

    def on_calibre_import(self) -> None:
        cfg = self.cfg
        target = self.ebook_target.currentData()

        def task(w):
            manifest = Manifest.load(cfg.manifest_path)
            if not manifest.books:
                raise RuntimeError("manifest 為空，請先掃描書庫。")
            if target == "calibre":
                result = calibre.import_drm_free(cfg, manifest)
                path = calibre.write_report(manifest, cfg)
            else:
                result = reader.open_drm_free(cfg, manifest, target="ade")
                path = reader.write_report(manifest, cfg, target="ade")
            w.log.emit(f"EPUB/PDF 交接報表：{path}")
            return result

        self._run(task, "交接 EPUB/PDF")

    def on_calibre_report(self) -> None:
        cfg = self.cfg
        target = self.ebook_target.currentData()

        def task(w):
            manifest = Manifest.load(cfg.manifest_path)
            if not manifest.books:
                raise RuntimeError("manifest 為空，請先掃描書庫。")
            if target == "calibre":
                path = calibre.write_report(manifest, cfg)
            else:
                path = reader.write_report(manifest, cfg, target="ade")
            w.log.emit(f"EPUB/PDF 交接報表：{path}")
            _open_folder(path.parent)
            return path

        self._run(task, "EPUB/PDF 報表")

    def on_acsm_preview(self) -> None:
        cfg = self.cfg
        limit = self.acsm_batch.value()
        include_opened = self.chk_include_opened_acsm.isChecked()

        def task(w):
            manifest = Manifest.load(cfg.manifest_path)
            if not manifest.books:
                raise RuntimeError("manifest 為空，請先掃描書庫。")
            result = acsm.open_acsm(
                cfg,
                manifest,
                dry_run=True,
                limit=limit,
                include_opened=include_opened,
            )
            path = acsm.write_report(manifest, cfg)
            plan = result.plan
            batch = min(limit, len(plan.openable))
            w.log.emit(
                f"本批可交接 {batch} 本、尚未交接 {len(plan.openable)} 本、"
                f"已送出 {len(plan.already_opened)} 本、檔案遺失 {len(plan.missing)} 本。"
            )
            w.log.emit(f"ACSM 交接報表：{path}")
            return result

        self._run(task, "檢查 ACSM")

    def on_acsm_open(self) -> None:
        cfg = self.cfg
        limit = self.acsm_batch.value()
        include_opened = self.chk_include_opened_acsm.isChecked()

        def task(w):
            manifest = Manifest.load(cfg.manifest_path)
            if not manifest.books:
                raise RuntimeError("manifest 為空，請先掃描書庫。")
            try:
                result = acsm.open_acsm(
                    cfg,
                    manifest,
                    limit=limit,
                    include_opened=include_opened,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"ACSM 交接失敗（exit {e.returncode}）。") from e
            except OSError as e:
                raise RuntimeError(f"ACSM 交接失敗：{e}") from e
            path = acsm.write_report(manifest, cfg)
            w.log.emit(f"已送出本批 ACSM：{result.opened} 本。")
            w.log.emit(f"ACSM 交接報表：{path}")
            return result

        self._run(task, "開啟 ACSM")

    def on_acsm_report(self) -> None:
        cfg = self.cfg

        def task(w):
            manifest = Manifest.load(cfg.manifest_path)
            if not manifest.books:
                raise RuntimeError("manifest 為空，請先掃描書庫。")
            path = acsm.write_report(manifest, cfg)
            w.log.emit(f"ACSM 交接報表：{path}")
            _open_folder(path.parent)
            return path

        self._run(task, "ACSM 報表")

    def on_stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self.append_log("已要求停止，將於目前這本完成後中止…")

    def on_export_report(self) -> None:
        manifest = Manifest.load(self.cfg.manifest_path)
        if not manifest.books:
            QMessageBox.information(
                self, tr("匯出報表"), tr("manifest 為空，請先掃描書庫。")
            )
            return
        csv_path = service.write_csv(manifest, self.cfg)
        html_path = service.write_html(manifest, self.cfg)
        self.append_log(f"已匯出：{csv_path}")
        self.append_log(f"已匯出：{html_path}")
        _open_folder(csv_path.parent)

    def on_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(tr("關於 OpenShelf"))
        box.setIconPixmap(app_icon().pixmap(64, 64))
        box.setTextFormat(Qt.RichText)
        desc = (
            "枚舉並批次匯出 Google Play 圖書：無 DRM 書下載 EPUB/PDF，"
            "DRM 書下載官方 .acsm 供 Adobe Digital Editions 閱讀。<br>"
            "不解析 ACSM、不抽金鑰、不移除任何保護。"
        )
        box.setText(
            "<b>OpenShelf</b><br>"
            f"{tr('版本')} {__version__}<br><br>{tr(desc)}"
        )
        box.setInformativeText(
            f"{tr('作者')}：{AUTHOR}<br>"
            f"{tr('授權')}：{LICENSE_NAME}<br>"
            f"GitHub：<a href='{GITHUB_URL}'>{GITHUB_URL}</a>"
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def _maybe_onboard(self) -> None:
        """首次啟動顯示三步驟導覽；之後不再顯示。"""
        if getattr(self, "_settings", None) is None or self._settings.value("onboarded"):
            return
        self._settings.setValue("onboarded", True)
        body = (
            "三步驟備份你的書庫：<br>"
            "1. <b>登入</b>：在瀏覽器登入一次 Google 帳號<br>"
            "2. <b>掃描書庫</b>：枚舉並分類你的書<br>"
            "3. <b>下載</b>：無 DRM 抓 EPUB/PDF，DRM 抓 .acsm 供 ADE 閱讀<br><br>"
            "現在就開始登入嗎？"
        )
        box = QMessageBox(self)
        box.setWindowTitle(tr("歡迎使用 OpenShelf"))
        box.setIconPixmap(app_icon().pixmap(64, 64))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b>{tr('歡迎使用 OpenShelf')}</b>")
        box.setInformativeText(tr(body))
        start = box.addButton(tr("開始登入"), QMessageBox.AcceptRole)
        box.addButton(tr("稍後"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is start:
            self.on_login()

    def on_check_update(self, manual: bool = False) -> None:
        req = QNetworkRequest(QUrl(update.RELEASES_API))
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        reply = self._nam.get(req)
        reply.finished.connect(
            lambda r=reply, m=manual: self._on_update_reply(r, m)
        )

    def _on_update_reply(self, reply, manual: bool) -> None:
        import json

        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                try:
                    data = json.loads(bytes(reply.readAll()) or b"{}")
                except ValueError:
                    data = {}
                tag = update.tag_from_release_json(data)
                if tag and update.is_newer(tag, __version__):
                    self.append_log(f"{tr('有新版本')}：{tag}　{update.RELEASES_PAGE}")
                    QMessageBox.information(
                        self,
                        tr("檢查更新"),
                        f"{tr('有新版本')}：{tag}<br>"
                        f"<a href='{update.RELEASES_PAGE}'>{update.RELEASES_PAGE}</a>",
                    )
                elif manual:
                    QMessageBox.information(
                        self, tr("檢查更新"), tr("已是最新版本。")
                    )
            elif manual:
                QMessageBox.information(
                    self, tr("檢查更新"), tr("檢查更新失敗（請稍後再試）。")
                )
        finally:
            reply.deleteLater()

    def on_lang_change(self) -> None:
        lang = self.lang_combo.currentData()
        set_language(lang)
        if getattr(self, "_settings", None) is not None:
            self._settings.setValue("language", lang)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """切換語言後重新套用所有介面字串。"""
        self.setWindowTitle(tr("OpenShelf"))
        self.btn_login.setText(tr("登入"))
        self.btn_scan.setText(tr("掃描書庫"))
        self.btn_export.setText(tr("下載"))
        self.btn_retry.setText(tr("重試失敗"))
        self.btn_retry.setToolTip(tr("只重新嘗試先前標記為失敗的書"))
        self.btn_stop.setText(tr("停止"))
        self.btn_update.setText(tr("檢查更新"))
        self.btn_about.setText(tr("ℹ 關於"))
        self.btn_about.setToolTip(tr("關於 OpenShelf（版本、作者、GitHub）"))
        self.btn_calibre_preview.setText(tr("檢查EPUB/PDF"))
        self.btn_calibre_import.setText(tr("交接EPUB/PDF"))
        self.btn_calibre_report.setText(tr("EPUB/PDF報表"))
        self.btn_acsm_preview.setText(tr("檢查ACSM"))
        self.btn_acsm_open.setText(tr("開啟ACSM"))
        self.btn_acsm_report.setText(tr("ACSM報表"))
        self.btn_refresh.setText(tr("重新整理"))
        self.btn_report.setText(tr("匯出CSV/HTML"))
        self.btn_report.setToolTip(tr("把書庫清單匯出為 CSV 與 HTML 報表並開啟資料夾"))
        self.chk_acsm.setText(tr("抓 .acsm"))
        self.chk_refresh.setText(tr("重抓逾時 .acsm"))
        self.chk_force_refresh.setText(tr("強制重抓 .acsm"))
        self.chk_force_refresh.setToolTip(
            tr("ADE 顯示 E_ADEPT_REQUEST_EXPIRED 時使用：不看有效天數，重新下載官方 .acsm 憑證")
        )
        self.chk_include_opened_acsm.setText(tr("包含已送出"))
        self.chk_include_opened_acsm.setToolTip(
            tr("ADE 當場失敗時使用：重新送出先前已交接的 .acsm")
        )
        self.chk_skipfail.setText(tr("略過已知失敗"))
        self.chk_cover.setText(tr("顯示封面"))
        self.chk_cover.setToolTip(
            tr("顯示書籍封面縮圖（需連網抓封面圖片，會快取於 output/.cover_cache）")
        )
        self.lbl_drmfmt.setText(tr("無 DRM 格式"))
        self.lbl_target.setText(tr("目標"))
        self.lbl_acsm_batch.setText(tr("批次"))
        self.acsm_batch.setToolTip(
            tr("一次送給 ADE 的 .acsm 數量；建議分批處理，避免憑證排隊過期")
        )
        self.lbl_search.setText(tr("搜尋"))
        self.lbl_filter.setText(tr("篩選"))
        self.lbl_lang.setText(tr("語言"))
        self.lbl_log.setText(tr("紀錄"))
        self.library_group.setTitle(tr("書庫"))
        self.download_group.setTitle(tr("下載"))
        self.handoff_tabs.setTabText(0, tr("ACSM"))
        self.handoff_tabs.setTabText(1, tr("EPUB/PDF"))
        self.search.setPlaceholderText(tr("搜尋 書名／作者／出版社"))
        self.table.setHorizontalHeaderLabels([tr(h) for h in _HEADERS])
        for i, (label, _v) in enumerate(_FILTERS):
            self.filter_combo.setItemText(i, tr(label))
        self.reload_manifest()


def _set_windows_app_id() -> None:
    """Windows：設定 AppUserModelID，讓工作列以本程式 icon 分組，而非 python.exe。"""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "OpenShelf.App"
            )
        except Exception:  # noqa: BLE001 — 設定失敗不影響功能
            pass


def run(config: Config) -> int:
    _set_windows_app_id()
    app = QApplication.instance() or QApplication([])
    settings = QSettings("OpenShelf", "OpenShelf")
    set_language(settings.value("language") or detect_default())
    app.setWindowIcon(app_icon())
    window = MainWindow(config)
    window.show()
    return app.exec()


def _open_folder(path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _plan_ready(plan) -> list:
    if hasattr(plan, "importable"):
        return plan.importable
    return plan.openable
