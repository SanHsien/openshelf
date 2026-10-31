"""Release workflow preflight 前置檢查之單元測試與 workflow 契約測試。"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.check_release_preflight import (
    ROOT,
    get_module_version,
    get_pyproject_version,
    verify_commit_on_main,
    verify_versions,
)


class ReleasePreflightVersionConsistencyTest(unittest.TestCase):
    def test_matching_versions_pass(self):
        ok, msg = verify_versions("v1.0.4", "1.0.4", "1.0.4")
        self.assertTrue(ok)
        self.assertEqual(msg, "版本一致")

    def test_mismatched_tag_version_fails(self):
        ok, msg = verify_versions("v9.9.9", "1.0.4", "1.0.4")
        self.assertFalse(ok)
        self.assertIn("版本不一致", msg)
        self.assertIn("v9.9.9", msg)

    def test_tag_without_v_prefix_fails(self):
        ok, msg = verify_versions("1.0.4", "1.0.4", "1.0.4")
        self.assertFalse(ok)
        self.assertIn("必須以 'v' 開頭", msg)

    def test_tag_empty_version_fails(self):
        ok, msg = verify_versions("v", "1.0.4", "1.0.4")
        self.assertFalse(ok)
        self.assertIn("缺少版本號", msg)

    def test_mismatched_pyproject_and_module_fails(self):
        ok, msg = verify_versions("v1.0.4", "1.0.4", "1.0.3")
        self.assertFalse(ok)
        self.assertIn("版本不一致", msg)

    def test_none_tag_with_matching_versions_passes(self):
        ok, msg = verify_versions(None, "1.0.4", "1.0.4")
        self.assertTrue(ok)

    def test_current_repo_versions_are_in_sync(self):
        pyproject_ver = get_pyproject_version(ROOT)
        module_ver = get_module_version(ROOT)
        self.assertEqual(pyproject_ver, module_ver)
        ok, msg = verify_versions(f"v{pyproject_ver}", pyproject_ver, module_ver)
        self.assertTrue(ok, msg)


class ReleasePreflightGitCommitTest(unittest.TestCase):
    def _git(self, repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def test_ancestry_on_and_off_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git(repo, "init", "-b", "main")
            self._git(repo, "commit", "--allow-empty", "-m", "base")
            on_main = self._git(repo, "rev-parse", "HEAD")
            self._git(repo, "checkout", "-b", "side")
            self._git(repo, "commit", "--allow-empty", "-m", "side")
            off_main = self._git(repo, "rev-parse", "HEAD")
            self.assertTrue(verify_commit_on_main(root=repo, commit=on_main, target_branch="main")[0])
            ok, msg = verify_commit_on_main(root=repo, commit=off_main, target_branch="main")
            self.assertFalse(ok)
            self.assertIn("祖先", msg)


class ReleaseWorkflowContractTest(unittest.TestCase):
    def setUp(self):
        self.workflow_path = ROOT / ".github" / "workflows" / "release.yml"
        self.content = self.workflow_path.read_text(encoding="utf-8")

    def test_preflight_job_is_defined(self):
        self.assertIn("preflight:", self.content)
        self.assertIn("runs-on: ubuntu-latest", self.content)

    def test_build_windows_depends_on_preflight(self):
        # build-windows 必須依賴 preflight
        windows_section = self.content.split("build-windows:", 1)[1]
        self.assertIn("needs: preflight", windows_section)

    def test_preflight_checks_out_full_depth(self):
        preflight_section = self.content.split("preflight:", 1)[1].split("build-windows:", 1)[0]
        self.assertIn("fetch-depth: 0", preflight_section)

    def test_preflight_runs_tests_and_consistency_tool(self):
        preflight_section = self.content.split("preflight:", 1)[1].split("build-windows:", 1)[0]
        self.assertIn("ruff check .", preflight_section)
        self.assertIn("python -m unittest discover", preflight_section)
        self.assertIn("python tools/check_release_preflight.py", preflight_section)


if __name__ == "__main__":
    unittest.main()
