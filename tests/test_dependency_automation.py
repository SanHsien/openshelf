"""依賴維護 workflow 的最低安全與生命週期契約。"""

import re
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


class GuardedMergeWorkflowTest(unittest.TestCase):
    def test_all_remote_actions_are_pinned_to_full_sha(self):
        mutable_uses = []
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            content = workflow.read_text(encoding="utf-8")
            for line in content.splitlines():
                match = re.search(r"uses:\s*([^@\s]+)@([^\s#]+)", line)
                if match and not re.fullmatch(r"[0-9a-fA-F]{40}", match.group(2)):
                    mutable_uses.append(f"{workflow.name}: {line.strip()}")

        self.assertEqual(mutable_uses, [])

    def test_review_uses_trusted_base_and_binds_policy_to_head_sha(self):
        content = (
            ROOT / ".github" / "workflows" / "dependabot-review.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("pull_request_target:", content)
        self.assertIn("github.event.pull_request.user.login == 'dependabot[bot]'", content)
        self.assertIn("github.repository == 'SanHsien/openshelf'", content)
        self.assertIn("github.event.pull_request.base.ref == 'main'", content)
        self.assertIn("github.event.pull_request.state == 'open'", content)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", content)
        self.assertIn("persist-credentials: false", content)
        self.assertIn("pull-requests: read", content)
        self.assertNotIn("pull-requests: write", content)
        self.assertIn("dependabot/fetch-metadata@", content)
        self.assertIn("tools/classify_dependabot_update.py", content)
        self.assertIn('--patch-file "$RUNNER_TEMP/dependabot.patch"', content)
        self.assertIn("HEAD_SHA: ${{ github.event.pull_request.head.sha }}", content)
        self.assertIn('name "Dependabot policy"', content)
        self.assertIn("dependencies-auto-merge", content)
        self.assertIn("dependencies-manual-review", content)
        self.assertIn("gh workflow run dependabot-merge.yml", content)

    def test_merge_gate_checks_identity_head_policy_ci_and_mergeability(self):
        content = (
            ROOT / ".github" / "workflows" / "dependabot-merge.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('workflows: ["CI"]', content)
        self.assertIn("group: dependabot-merge-queue", content)
        self.assertIn(
            "EVENT_PR: ${{ github.event.workflow_run.pull_requests[0].number }}",
            content,
        )
        self.assertIn('elif [ -n "$EVENT_PR" ]', content)
        self.assertIn("--author app/dependabot", content)
        self.assertIn('author" != "app/dependabot"', content)
        self.assertIn('base" != "main"', content)
        self.assertIn('state" != "OPEN"', content)
        self.assertIn("dependencies-auto-merge", content)
        self.assertIn("dependencies-manual-review", content)
        self.assertIn("dependencies-rebase-requested", content)
        self.assertIn("Dependabot policy", content)
        for check_name in ("test (3.11)", "test (3.12)", "test (3.13)"):
            self.assertIn(check_name, content)
            self.assertGreaterEqual(content.count(check_name), 2)
        self.assertIn("actions/workflows/ci.yml/runs?head_sha=", content)
        self.assertIn('.event == "pull_request"', content)
        self.assertIn(".head_sha == $head", content)
        self.assertIn("any(.pull_requests[]?; .number == $pr)", content)
        self.assertIn(
            "sort_by(.created_at) | reverse | .[0] // {}",
            content,
        )
        self.assertIn(
            "目前 head SHA 的最新 CI 尚未成功",
            content,
        )
        self.assertNotIn("gh pr checks", content)
        self.assertIn("--match-head-commit", content)
        self.assertIn("--squash", content)
        self.assertIn("--delete-branch", content)
        self.assertIn("@dependabot rebase", content)
        self.assertNotIn("actions/checkout", content)

    def test_workflow_run_pr_precedes_fallback_queue(self):
        content = (
            ROOT / ".github" / "workflows" / "dependabot-merge.yml"
        ).read_text(encoding="utf-8")

        event_branch = content.index('elif [ -n "$EVENT_PR" ]')
        fallback_query = content.index("gh pr list")
        self.assertLess(event_branch, fallback_query)
        self.assertIn('pr_number="$EVENT_PR"', content[event_branch:fallback_query])


if __name__ == "__main__":
    unittest.main()
