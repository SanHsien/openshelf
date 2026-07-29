#!/usr/bin/env python3
"""檢查 OpenShelf 直接依賴是否有較新版本。

此工具只讀取 pyproject.toml 的宣告並查詢 PyPI JSON API，不使用目前
電腦已安裝的套件版本。它只輸出維護報告，不會修改依賴或自動合併 PR。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tomllib
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent

_REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)$")
_MINIMUM_RE = re.compile(
    r"(>=|>|==|~=)\s*([0-9][0-9A-Za-z.!+_-]*(?:\.[0-9A-Za-z!+_-]+)*)"
)


def normalize_package_name(package_name: str) -> str:
    """依 Python 套件名稱規則正規化連字號、底線與大小寫。"""
    return re.sub(r"[-_.]+", "-", package_name).lower()


def is_newer_version(latest: str, current: str) -> bool:
    """依 PEP 440 判斷 latest 是否比 current 新。"""
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return False


def _parse_requirements(
    requirements: Iterable[str],
    group: str,
) -> list[dict[str, str]]:
    packages = []
    for requirement in requirements:
        match = _REQUIREMENT_RE.match(requirement)
        if not match:
            continue
        name, specifiers = match.groups()
        minimum_match = _MINIMUM_RE.search(specifiers)
        packages.append(
            {
                "name": name,
                "minimum": minimum_match.group(2) if minimum_match else "",
                "requirement": requirement,
                "group": group,
            }
        )
    return packages


def load_direct_dependencies(
    pyproject_path: Path = ROOT / "pyproject.toml",
) -> list[dict[str, str]]:
    """讀取 runtime、optional 與 build-system 直接依賴。"""
    with pyproject_path.open("rb") as file:
        data = tomllib.load(file)

    project = data.get("project", {})
    packages = _parse_requirements(project.get("dependencies", []), "runtime")

    for group, requirements in project.get("optional-dependencies", {}).items():
        packages.extend(_parse_requirements(requirements, f"optional:{group}"))

    build_system = data.get("build-system", {})
    packages.extend(
        _parse_requirements(build_system.get("requires", []), "build-system")
    )
    return packages


def fetch_pypi_version(
    package_name: str,
    timeout: float = 10.0,
) -> str | None:
    """回傳 PyPI 最新穩定版本；查不到時回傳 None。"""
    quoted_name = urllib.parse.quote(package_name, safe="")
    request = urllib.request.Request(
        f"https://pypi.org/pypi/{quoted_name}/json",
        headers={
            "Accept": "application/json",
            "User-Agent": "openshelf-dependency-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            data = json.loads(response.read().decode("utf-8"))
        return data.get("info", {}).get("version")
    except (OSError, ValueError):
        return None


def collect_status(
    packages: Iterable[dict[str, str]],
) -> list[dict[str, object]]:
    """收集 repo 宣告基線、PyPI 最新版與維護狀態。"""
    rows = []
    for package in packages:
        minimum = package["minimum"]
        latest = fetch_pypi_version(package["name"])
        check_failed = not minimum or latest is None
        outdated = bool(
            minimum
            and latest
            and is_newer_version(str(latest), minimum)
        )
        rows.append(
            {
                **package,
                "latest": latest or "unknown",
                "outdated": outdated,
                "check_failed": check_failed,
            }
        )
    return rows


def render_markdown(rows: list[dict[str, object]]) -> str:
    """輸出 GitHub issue 與 Actions summary 可讀的 Markdown。"""
    lines = [
        "# OpenShelf 依賴新鮮度檢查",
        "",
        "| 套件 | 類別 | Repo 宣告 | PyPI 最新 | 狀態 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row["check_failed"]:
            status = "檢查失敗"
        elif row["outdated"]:
            status = "需要維護"
        else:
            status = "OK"
        lines.append(
            f"| `{row['name']}` | `{row['group']}` | "
            f"`{row['requirement']}` | `{row['latest']}` | {status} |"
        )
    lines.extend(
        [
            "",
            "本報告只比較 repo 宣告與 PyPI，不使用 runner 或維護者電腦目前安裝的版本。",
            "版本較新只表示需要評估，不代表可以直接升級。",
            "",
            "## 處理流程",
            "",
            "1. 查看同批 Dependabot PR、套件 changelog、Python 3.11–3.13 與目標平台相容性。",
            "2. 只有 CI allowlist 中的 maintenance minor／patch，以及低權限 CI workflow 的",
            "   GitHub Actions minor／patch 可進入 guarded auto-merge；其餘一律人工審查。",
            "3. 通過完整 CI；會影響登入、下載、GUI 或打包鏈時，再完成對應實機／Release 驗證。",
            "4. 直接依賴皆更新且沒有 open Dependabot PR 時，排程會自動關閉維護 issue。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_github_output(
    outdated: bool,
    check_failed: bool,
    report_path: Path,
) -> None:
    """寫入 GitHub Actions output。"""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"outdated={'true' if outdated else 'false'}\n")
        output.write(f"check_failed={'true' if check_failed else 'false'}\n")
        output.write(
            f"needs_attention={'true' if outdated or check_failed else 'false'}\n"
        )
        output.write(f"report_path={report_path.as_posix()}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="檢查 OpenShelf pyproject.toml 直接依賴是否有新版"
    )
    parser.add_argument(
        "--output",
        default="dependency-freshness-report.md",
        help="Markdown 報告輸出路徑",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="同時寫入 GitHub Actions output",
    )
    args = parser.parse_args()

    packages = load_direct_dependencies()
    rows = collect_status(packages)
    report = render_markdown(rows)
    output_path = Path(args.output)
    output_path.write_text(report, encoding="utf-8")
    print(report)

    outdated = any(bool(row["outdated"]) for row in rows)
    check_failed = not rows or any(bool(row["check_failed"]) for row in rows)
    if args.github_output:
        write_github_output(outdated, check_failed, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
