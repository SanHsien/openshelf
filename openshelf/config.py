"""讀取 config.toml 並套用預設值。"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# 設定檔搜尋順序：環境指定 > 專案根目錄
DEFAULT_CONFIG_NAME = "config.toml"

_DEFAULTS = {
    "output_dir": "output",
    "profile_dir": ".profile",
    "storage_state": "storage_state.json",
    "prefer_format": "epub",
    "include_acsm": True,
    "throttle_seconds": 2.0,
    "download_timeout": 120,
    "download_retries": 3,
    "acsm_valid_days": 7,
    "calibredb_path": "",
    "calibre_library": "",
    "ade_path": "",
}


@dataclass
class Config:
    """執行期設定。所有路徑都已解析為絕對路徑。"""

    base_dir: Path
    output_dir: Path
    profile_dir: Path
    storage_state: Path
    prefer_format: str
    include_acsm: bool
    throttle_seconds: float
    download_timeout: int
    download_retries: int
    acsm_valid_days: int
    calibredb_path: Path | None
    calibre_library: Path | None
    ade_path: Path | None

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "manifest.json"


def _project_root() -> Path:
    # PyInstaller 打包後：以 exe 所在目錄為基準，讓 output/ 與登入態落在 exe 旁邊
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 開發時：openshelf/config.py -> 專案根目錄
    return Path(__file__).resolve().parent.parent


def load_config(config_path: str | Path | None = None) -> Config:
    """載入設定。找不到設定檔時全部採用預設值。"""
    root = _project_root()
    path = Path(config_path) if config_path else root / DEFAULT_CONFIG_NAME

    data = dict(_DEFAULTS)
    if path.is_file():
        with path.open("rb") as fh:
            data.update(tomllib.load(fh))

    base = path.parent if path.is_file() else root

    def _resolve(value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (base / p)

    def _resolve_optional(value) -> Path | None:
        if value is None or str(value).strip() == "":
            return None
        return _resolve(str(value))

    prefer = str(data["prefer_format"]).lower()
    if prefer not in {"epub", "pdf"}:
        prefer = "epub"

    return Config(
        base_dir=base,
        output_dir=_resolve(str(data["output_dir"])),
        profile_dir=_resolve(str(data["profile_dir"])),
        storage_state=_resolve(str(data["storage_state"])),
        prefer_format=prefer,
        include_acsm=bool(data["include_acsm"]),
        throttle_seconds=float(data["throttle_seconds"]),
        download_timeout=int(data["download_timeout"]),
        download_retries=int(data["download_retries"]),
        acsm_valid_days=int(data["acsm_valid_days"]),
        calibredb_path=_resolve_optional(data.get("calibredb_path")),
        calibre_library=_resolve_optional(data.get("calibre_library")),
        ade_path=_resolve_optional(data.get("ade_path")),
    )
