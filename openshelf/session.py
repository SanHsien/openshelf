"""把 Playwright 保存的 storage_state 載入為帶登入態的 httpx client。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx

from .config import Config

# 貼近一般瀏覽器的標頭，降低被當成異常流量的機率
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


class NotLoggedIn(RuntimeError):
    """找不到登入態，需先執行 openshelf login。"""


class SessionExpired(RuntimeError):
    """登入態被伺服器拒絕（401/403），多半已過期，需重新 openshelf login。"""


def _load_cookies(storage_state: Path) -> list[dict]:
    if not storage_state.is_file():
        raise NotLoggedIn(
            f"找不到登入態 {storage_state}，請先執行：openshelf login"
        )
    data = json.loads(storage_state.read_text(encoding="utf-8"))
    return data.get("cookies", [])


def _check_windows_storage_permissions(storage_state: Path) -> str | None:
    """唯讀檢查 ACL；以 SID 判斷，不依賴作業系統顯示語言。"""
    literal = str(storage_state.resolve()).replace("'", "''")
    script = r"""
$ErrorActionPreference = 'Stop'
Import-Module "$PSHOME\Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
$acl = Get-Acl -LiteralPath '__PATH__'
$raw = New-Object System.Security.AccessControl.RawSecurityDescriptor ($acl.Sddl)
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) | ForEach-Object {
    @{sid=$_.IdentityReference.Value; rights=[long]$_.FileSystemRights;
      type=[int]$_.AccessControlType; inheritOnly=(($_.PropagationFlags -band 2) -ne 0)}
})
@{currentUser=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value;
  nullDacl=($null -eq $raw.DiscretionaryAcl); rules=$rules} | ConvertTo-Json -Depth 4 -Compress
""".replace('__PATH__', literal)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, check=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads(result.stdout)
        trusted = {data["currentUser"], "S-1-5-18", "S-1-5-32-544"}
        # 不模擬群組成員與 Deny 的有效權限；發現其他讀取 Allow 就保守提示。
        broad = data["nullDacl"] or any(
            rule["type"] == 0 and not rule["inheritOnly"]
            and rule["rights"] & 0x90000001 and rule["sid"] not in trusted
            for rule in data["rules"]
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return (
            f"無法確認登入態檔案 {storage_state} 的 Windows ACL；"
            "請在檔案內容的「安全性」頁籤確認僅目前使用者、SYSTEM 與系統管理員可讀取。"
        )
    if broad:
        return (
            f"登入態檔案 {storage_state} 的 Windows ACL 可能過寬，"
            "其他本機使用者或群組具有讀取 Allow；請在檔案內容的「安全性」頁籤檢查"
            "（含繼承權限），建議僅保留目前使用者、SYSTEM 與系統管理員的讀取權限。"
            "此檢查採保守判斷，未計算群組與 Deny 的有效權限。"
        )
    return None


def check_storage_permissions(storage_state: Path) -> str | None:
    """檢查 POSIX mode 或 Windows ACL；只讀取權限，不讀取 cookie。"""
    if not storage_state.is_file():
        return None
    if sys.platform.startswith("win"):
        return _check_windows_storage_permissions(storage_state)
    try:
        mode = storage_state.stat().st_mode
    except OSError:
        return None
    if mode & 0o077:
        current_octal = oct(mode & 0o777)
        return (
            f"登入態檔案 {storage_state} 權限過寬（{current_octal}），"
            f"其他本機使用者可能可讀取敏感 cookie；建議設為 600（chmod 600 {storage_state}）。"
        )
    return None


def build_client(config: Config) -> httpx.Client:
    """建立沿用登入態 cookies 的 httpx client。"""
    cookies = _load_cookies(config.storage_state)
    jar = httpx.Cookies()
    for c in cookies:
        jar.set(
            name=c["name"],
            value=c["value"],
            domain=c.get("domain", "").lstrip("."),
            path=c.get("path", "/"),
        )
    return httpx.Client(
        headers=DEFAULT_HEADERS,
        cookies=jar,
        timeout=config.download_timeout,
        follow_redirects=True,
    )
