#!/usr/bin/env python3
"""依依賴類型、版本幅度與變更範圍判斷 Dependabot PR 是否可自動合併。"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

AUTO_MERGE_LABEL = "dependencies-auto-merge"
MANUAL_REVIEW_LABEL = "dependencies-manual-review"
SEMVER_UPDATE_TYPES = {
    "version-update:semver-patch",
    "version-update:semver-minor",
    "version-update:semver-major",
}
SAFE_MINOR_PATCH_TYPES = SEMVER_UPDATE_TYPES - {"version-update:semver-major"}
PIP_MANIFESTS = {"pyproject.toml"}
CI_EXERCISED_MAINTENANCE_PACKAGES = {"packaging"}
SAFE_CI_ACTIONS = {"actions/checkout", "actions/setup-python"}
SAFE_ACTION_WORKFLOWS = {".github/workflows/ci.yml"}
ACTION_REF_RE = re.compile(
    r"^(?:-\s*)?uses:\s*(?P<action>[^@\s]+)@(?P<ref>[^\s#]+)(?:\s+#.*)?$"
)


def _manual(reason: str) -> dict[str, str]:
    return {
        "decision": "manual",
        "label": MANUAL_REVIEW_LABEL,
        "reason": reason,
    }


def _normalize_package_name(package_name: str) -> str:
    return re.sub(r"[-_.]+", "-", package_name).lower()


def _action_patch_only_updates_pinned_refs(
    changed_patch: str,
    expected_actions: set[str],
) -> bool:
    changed_lines = [
        line
        for line in changed_patch.splitlines()
        if line[:1] in {"+", "-"}
        and not line.startswith(("+++", "---"))
    ]
    if not changed_lines or any("uses:" not in line for line in changed_lines):
        return False

    added = [
        ACTION_REF_RE.fullmatch(line[1:].strip())
        for line in changed_lines
        if line.startswith("+")
    ]
    deleted = [
        ACTION_REF_RE.fullmatch(line[1:].strip())
        for line in changed_lines
        if line.startswith("-")
    ]
    if not added or not deleted or any(match is None for match in added + deleted):
        return False

    added_actions = Counter(
        match.group("action").lower()
        for match in added
        if match is not None
    )
    deleted_actions = Counter(
        match.group("action").lower()
        for match in deleted
        if match is not None
    )
    return (
        added_actions == deleted_actions
        and set(added_actions) == expected_actions
        and all(
            re.fullmatch(r"[0-9a-fA-F]{40}", match.group("ref"))
            for match in added
            if match is not None
        )
    )


def classify_update(
    ecosystem: str,
    dependency_type: str,
    update_type: str,
    changed_files: Iterable[str],
    dependency_names: Iterable[str],
    changed_patch: str = "",
) -> dict[str, str]:
    """回傳 ``auto_merge`` 或 ``manual``；無法證明低風險時一律人工審查。"""
    files = {Path(path).as_posix() for path in changed_files if path}
    if not files:
        return _manual("沒有可驗證的變更檔案，保留人工審查。")
    if update_type not in SEMVER_UPDATE_TYPES:
        return _manual("無法確認版本更新幅度，保留人工審查。")

    if ecosystem == "pip":
        if not files.issubset(PIP_MANIFESTS):
            return _manual("Python 依賴 PR 超出 pyproject.toml 範圍。")
        names = {
            _normalize_package_name(name)
            for name in dependency_names
            if name
        }
        if not names:
            return _manual("沒有可驗證的依賴名稱，保留人工審查。")
        if dependency_type == "direct:production":
            return _manual(
                "執行期或建置依賴會影響登入、下載、GUI 或發布產物，"
                "保留人工與實機審查。"
            )
        if dependency_type != "direct:development":
            return _manual("不是可自動處理的直接 maintenance 依賴。")
        if update_type not in SAFE_MINOR_PATCH_TYPES:
            return _manual("maintenance major 更新保留人工審查。")
        if not names.issubset(CI_EXERCISED_MAINTENANCE_PACKAGES):
            return _manual("包含未被必要 CI 直接執行的 maintenance／發布工具。")
        return {
            "decision": "auto_merge",
            "label": AUTO_MERGE_LABEL,
            "reason": (
                "maintenance minor 或 patch 只修改 pyproject.toml，"
                "且由 Python 3.11–3.13 CI 直接執行與測試。"
            ),
        }

    if ecosystem == "github-actions":
        if update_type not in SAFE_MINOR_PATCH_TYPES:
            return _manual("GitHub Actions major 更新可能改變 workflow 行為。")
        if files != SAFE_ACTION_WORKFLOWS:
            return _manual(
                "GitHub Actions PR 超出允許的低權限 CI workflow 檔案範圍；"
                "privileged／Release workflow 保留人工審查。"
            )
        names = {
            _normalize_package_name(name)
            for name in dependency_names
            if name
        }
        if not names or not names.issubset(SAFE_CI_ACTIONS):
            return _manual("GitHub Action 不在低權限 CI allowlist。")
        if not _action_patch_only_updates_pinned_refs(
            changed_patch,
            names,
        ):
            return _manual(
                "GitHub Action PR 只能更新 uses ref，且新值必須是完整 commit SHA。"
            )
        return {
            "decision": "auto_merge",
            "label": AUTO_MERGE_LABEL,
            "reason": "GitHub Actions minor 或 patch 更新，且只修改 workflow。",
        }

    return _manual("未列入自動核准政策的套件生態系。")


def write_github_output(result: dict[str, str]) -> None:
    """把判斷結果寫入 GitHub Actions output。"""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as output:
        output.writelines(
            f"{key}={result[key]}\n"
            for key in ("decision", "label", "reason")
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="判斷 Dependabot PR 是否可進入 guarded auto-merge"
    )
    parser.add_argument("--ecosystem", required=True)
    parser.add_argument("--dependency-type", required=True)
    parser.add_argument("--update-type", required=True)
    parser.add_argument("--dependency-names", required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--patch-file")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()

    result = classify_update(
        ecosystem=args.ecosystem,
        dependency_type=args.dependency_type,
        update_type=args.update_type,
        changed_files=args.changed_file,
        dependency_names=[
            name.strip()
            for name in args.dependency_names.split(",")
        ],
        changed_patch=(
            Path(args.patch_file).read_text(encoding="utf-8")
            if args.patch_file
            else ""
        ),
    )
    print(json.dumps(result, ensure_ascii=False))
    if args.github_output:
        write_github_output(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
