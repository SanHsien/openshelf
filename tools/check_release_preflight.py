#!/usr/bin/env python3
"""Release workflow 前置檢查工具。

驗證 Release 條件：
1. tag、pyproject.toml 與 openshelf.__version__ 三者一致。
2. tag 指向 origin/main 上的 commit，避免任意 v* tag 發布未審查二進位。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def get_pyproject_version(root: Path = ROOT) -> str:
    """從 pyproject.toml 讀取 project.version。"""
    pyproject_path = root / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(f"找不到 pyproject.toml：{pyproject_path}")
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    version = data.get("project", {}).get("version")
    if not version:
        raise ValueError(f"pyproject.toml 中缺少 project.version：{pyproject_path}")
    return str(version).strip()


def get_module_version(root: Path = ROOT) -> str:
    """從 openshelf/__init__.py 讀取 __version__。"""
    init_path = root / "openshelf" / "__init__.py"
    if not init_path.exists():
        raise FileNotFoundError(f"找不到 openshelf/__init__.py：{init_path}")
    content = init_path.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        raise ValueError(f"在 {init_path} 中找不到 __version__ 定義")
    return match.group(1).strip()


def resolve_tag(explicit_tag: str | None = None, root: Path = ROOT) -> str | None:
    """解析當前要檢查的 tag 名稱。"""
    if explicit_tag:
        return explicit_tag.strip()

    # GitHub Actions 環境變數
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/"):
        return ref[len("refs/tags/") :].strip()

    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    if ref_type == "tag" and ref_name:
        return ref_name.strip()

    # 嘗試從本機 git exact-match tag 取得
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--exact-match", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass

    return None


def verify_versions(
    tag: str | None,
    pyproject_version: str,
    module_version: str,
) -> tuple[bool, str]:
    """比對 tag、pyproject.toml 與 openshelf.__version__ 是否一致。"""
    if pyproject_version != module_version:
        return (
            False,
            f"版本不一致：pyproject.toml ({pyproject_version}) != "
            f"openshelf.__version__ ({module_version})",
        )

    if tag is not None:
        if not tag.startswith("v"):
            return (
                False,
                f"Release tag 格式不正確：'{tag}' 必須以 'v' 開頭（例如 v1.0.4）",
            )
        tag_version = tag[1:].strip()
        if not tag_version:
            return (
                False,
                f"Release tag 格式不正確：'{tag}' 缺少版本號",
            )
        if tag_version != pyproject_version:
            return (
                False,
                f"版本不一致：tag '{tag}' 表示版本 '{tag_version}'，"
                f"但 pyproject.toml 為 '{pyproject_version}'",
            )
        if tag_version != module_version:
            return (
                False,
                f"版本不一致：tag '{tag}' 表示版本 '{tag_version}'，"
                f"但 openshelf.__version__ 為 '{module_version}'",
            )

    return True, "版本一致"


def resolve_main_branch(root: Path = ROOT, preferred: str = "origin/main") -> str:
    """尋找可用於比對的 main 分支參照（優先 origin/main，fallback main）。"""
    for branch in (preferred, "origin/main", "main"):
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return branch
    raise RuntimeError("找不到可用的 main 分支參照（已嘗試 origin/main 與 main）")


def verify_commit_on_main(
    root: Path = ROOT,
    commit: str = "HEAD",
    target_branch: str | None = None,
) -> tuple[bool, str]:
    """驗證指定的 commit 是否是 target_branch（main）歷史上的 commit。"""
    try:
        main_ref = (
            target_branch
            if target_branch
            else resolve_main_branch(root=root)
        )
    except Exception as exc:
        return False, str(exc)

    rev_proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", commit],
        capture_output=True,
        text=True,
        check=False,
    )
    if rev_proc.returncode != 0:
        return False, f"無法解析 commit 參照：'{commit}'"
    commit_sha = rev_proc.stdout.strip()

    merge_base_proc = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", commit_sha, main_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if merge_base_proc.returncode == 0:
        return True, f"Commit {commit_sha} 確認屬於 {main_ref} 分支歷史。"

    return (
        False,
        f"Commit {commit_sha} 不是 {main_ref} 的祖先（tag 必須指向 main 上的 commit，避免任意 tag 發布未審查二進位）。",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release workflow 前置檢查")
    parser.add_argument(
        "--tag",
        dest="tag",
        default=None,
        help="手動指定 release tag（例如 v1.0.4）",
    )
    parser.add_argument(
        "--commit",
        dest="commit",
        default="HEAD",
        help="手動指定 commit 參照（預設 HEAD）",
    )
    parser.add_argument(
        "--target-branch",
        dest="target_branch",
        default=None,
        help="比對的目標分支（預設自動尋找 origin/main 或 main）",
    )
    parser.add_argument(
        "--skip-git-check",
        action="store_true",
        help="跳過 git 分支祖先檢查（僅驗證版本一致性）",
    )
    parser.add_argument(
        "--require-tag",
        action="store_true",
        help="強制要求必須有 tag（非 tag 觸發時報錯）",
    )
    parser.add_argument(
        "--repo-dir",
        dest="repo_dir",
        type=Path,
        default=ROOT,
        help="專案根目錄路徑",
    )

    args = parser.parse_args(argv)
    root = args.repo_dir.resolve()

    try:
        pyproject_ver = get_pyproject_version(root)
        module_ver = get_module_version(root)
    except Exception as exc:
        print(f"[ERROR] 讀取版本資訊失敗：{exc}", file=sys.stderr)
        return 1

    tag = resolve_tag(args.tag, root=root)

    if args.require_tag and not tag:
        print("[ERROR] 缺少 release tag（--require-tag 已啟用）", file=sys.stderr)
        return 1

    # 1. 驗證版本一致性
    ok, msg = verify_versions(tag, pyproject_ver, module_ver)
    if not ok:
        print(f"[ERROR] {msg}", file=sys.stderr)
        return 1

    if tag:
        print(f"[OK] 版本一致：tag={tag}, pyproject.toml={pyproject_ver}, openshelf.__version__={module_ver}")
    else:
        print(
            f"[INFO] 未指定 tag（非 tag 觸發），已驗證 package metadata 與模組版本一致：{pyproject_ver}"
        )

    # 2. 驗證 git commit 是否在 main 上
    if not args.skip_git_check:
        # 不論是否為 tag 觸發，除非加 --skip-git-check，一律檢查 --commit（預設 HEAD）是 main 的祖先
        ok, msg = verify_commit_on_main(
            root=root,
            commit=args.commit,
            target_branch=args.target_branch,
        )
        if not ok:
            print(f"[ERROR] {msg}", file=sys.stderr)
            return 1
        print(f"[OK] {msg}")

    print("[OK] Release 前置檢查全數通過。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
