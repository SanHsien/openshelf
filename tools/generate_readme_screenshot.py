"""Generate the README main-window screenshot with deterministic demo data.

This script intentionally uses a temporary config/output directory. It never
reads the user's real OpenShelf output, Google session, ADE files, or local
library. The screenshot is captured from the Qt widget itself, not from the
desktop, so other windows and private data cannot appear in the image.
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from openshelf.config import Config
from openshelf.manifest import BookEntry, Manifest, now_iso
from openshelf.ui import main_window
from openshelf.ui.i18n import set_language


def _write_demo_manifest(output_dir: Path) -> None:
    files = {
        "pride_and_prejudice.epub": b"PK\x03\x04 demo epub",
        "time_machine.acsm": b"<fulfillmentToken/>",
    }
    for name, data in files.items():
        (output_dir / name).write_bytes(data)

    manifest = Manifest(output_dir / "manifest.json")
    entries = [
        BookEntry(
            "demo-pride",
            title="Pride and Prejudice",
            author="Jane Austen",
            publisher="Public Domain Library",
            category="drm_free",
            file_path="pride_and_prejudice.epub",
            downloaded_at=now_iso(),
        ),
        BookEntry(
            "demo-time-machine",
            title="The Time Machine",
            author="H. G. Wells",
            publisher="Public Domain Library",
            category="acsm",
            file_path="time_machine.acsm",
            downloaded_at=now_iso(),
        ),
        BookEntry(
            "demo-no-export",
            title="No Export Example",
            author="OpenShelf Demo",
            publisher="Demo Publisher",
            category="no_export",
            note="Google did not provide an export option.",
        ),
        BookEntry(
            "demo-retry",
            title="Retry Needed Example",
            author="OpenShelf Demo",
            publisher="Demo Publisher",
            category="failed",
            note="HTTPStatusError: 503",
        ),
    ]
    for entry in entries:
        manifest.upsert(entry)
    manifest.save()


def _config(base_dir: Path) -> Config:
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        base_dir=base_dir,
        output_dir=output_dir,
        profile_dir=base_dir / ".profile",
        storage_state=base_dir / "storage_state.json",
        prefer_format="epub",
        include_acsm=True,
        throttle_seconds=0,
        download_timeout=1,
        download_retries=1,
        acsm_valid_days=7,
        calibredb_path=None,
        calibre_library=None,
        ade_path=None,
    )


def generate(output_path: Path) -> Path:
    base_dir = Path(tempfile.mkdtemp(prefix="openshelf-readme-shot-"))
    cfg = _config(base_dir)
    _write_demo_manifest(cfg.output_dir)

    set_language("zh")
    main_window.MainWindow.on_check_update = lambda self, manual=False: None
    main_window.MainWindow._maybe_onboard = lambda self: None

    app = QApplication.instance() or QApplication([])
    window = main_window.MainWindow(cfg)
    window.resize(1600, 820)
    window.handoff_tabs.setCurrentIndex(0)
    window.acsm_batch.setValue(25)
    window.chk_cover.setChecked(False)
    window.logview.clear()
    window.reload_manifest()
    window.show()

    for _ in range(8):
        app.processEvents()
        time.sleep(0.05)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(output_path), "PNG"):
        raise RuntimeError(f"Failed to save screenshot: {output_path}")
    window.close()
    app.processEvents()
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/screenshots/main-window.png"),
        help="Screenshot output path.",
    )
    args = parser.parse_args()
    print(generate(args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
