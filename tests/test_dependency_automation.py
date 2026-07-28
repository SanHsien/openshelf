"""依賴維護 workflow 的最低安全與生命週期契約。"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class DependabotConfigurationTest(unittest.TestCase):
    def test_tracks_python_and_github_actions_without_auto_merge(self):
        content = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

        self.assertIn('package-ecosystem: "pip"', content)
        self.assertIn('package-ecosystem: "github-actions"', content)
        self.assertIn('timezone: "Asia/Taipei"', content)
        self.assertNotIn("auto-merge", content)


class FreshnessWorkflowTest(unittest.TestCase):
    def test_ci_installs_maintenance_dependency_for_checker_tests(self):
        content = (
            ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('pip install -e ".[maintenance]"', content)

    def test_schedule_owns_one_issue_and_uses_minimal_permissions(self):
        content = (
            ROOT / ".github" / "workflows" / "dependency-freshness.yml"
        ).read_text(encoding="utf-8")
        top_level = content.split("jobs:", 1)[0]
        mutation_job = content.split("maintain-issue:", 1)[1]

        self.assertIn("schedule:", content)
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("issues: write", content)
        self.assertNotIn("issues: write", top_level)
        self.assertNotIn("pip install", mutation_job)
        self.assertNotIn("actions/checkout", mutation_job)
        self.assertIn("pull-requests: read", content)
        self.assertIn("contents: read", content)
        self.assertNotIn("contents: write", content)
        self.assertIn("pull_request_target:", content)
        self.assertIn(
            "github.event.pull_request.user.login == 'dependabot[bot]'",
            content,
        )
        self.assertIn("ref: main", content)
        self.assertIn("persist-credentials: false", content)
        self.assertIn("cancel-in-progress: false", content)
        self.assertIn("needs: check", content)
        self.assertIn("report_base64:", content)
        self.assertIn("GH_REPO: ${{ github.repository }}", content)
        self.assertIn("--author app/dependabot", content)
        self.assertIn("--label dependency-freshness-tracker", content)
        self.assertIn("select(.title == ", content)
        self.assertIn('open_pr_count="$(gh pr list', content)
        self.assertIn("gh issue reopen", content)
        self.assertIn("gh issue close", content)
        self.assertIn("checked_sha", content)
        self.assertIn("latest_sha", content)

    def test_workflow_runs_checker_and_tracks_its_own_changes(self):
        content = (
            ROOT / ".github" / "workflows" / "dependency-freshness.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("tools/check_dependency_freshness.py", content)
        self.assertIn("pyproject.toml", content)
        self.assertIn(".github/dependabot.yml", content)
        self.assertIn(".github/workflows/dependency-freshness.yml", content)


if __name__ == "__main__":
    unittest.main()
