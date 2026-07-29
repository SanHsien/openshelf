"""Dependabot guarded auto-merge 的純政策測試。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import classify_dependabot_update as policy


class DependabotPolicyTest(unittest.TestCase):
    def classify(
        self,
        *,
        ecosystem="pip",
        dependency_type="direct:development",
        update_type="version-update:semver-patch",
        changed_files=None,
        dependency_names=None,
        changed_patch="",
    ):
        return policy.classify_update(
            ecosystem=ecosystem,
            dependency_type=dependency_type,
            update_type=update_type,
            changed_files=(
                ["pyproject.toml"]
                if changed_files is None
                else changed_files
            ),
            dependency_names=(
                ["packaging"]
                if dependency_names is None
                else dependency_names
            ),
            changed_patch=changed_patch,
        )

    def test_allows_ci_exercised_maintenance_patch_and_minor(self):
        for update_type in (
            "version-update:semver-patch",
            "version-update:semver-minor",
        ):
            with self.subTest(update_type=update_type):
                result = self.classify(update_type=update_type)
                self.assertEqual(result["decision"], "auto_merge")
                self.assertEqual(result["label"], "dependencies-auto-merge")

    def test_requires_manual_review_for_maintenance_major(self):
        result = self.classify(update_type="version-update:semver-major")

        self.assertEqual(result["decision"], "manual")
        self.assertIn("major", result["reason"])

    def test_requires_manual_review_for_runtime_dependency(self):
        result = self.classify(
            dependency_type="direct:production",
            dependency_names=["httpx"],
        )

        self.assertEqual(result["decision"], "manual")
        self.assertIn("執行期", result["reason"])

    def test_requires_manual_review_for_gui_and_build_dependencies(self):
        for dependency in ("PySide6", "pyinstaller", "setuptools"):
            with self.subTest(dependency=dependency):
                result = self.classify(dependency_names=[dependency])
                self.assertEqual(result["decision"], "manual")

    def test_allows_github_actions_patch_or_minor_in_workflow_scope(self):
        for update_type in (
            "version-update:semver-patch",
            "version-update:semver-minor",
        ):
            with self.subTest(update_type=update_type):
                result = self.classify(
                    ecosystem="github-actions",
                    dependency_type="direct:production",
                    update_type=update_type,
                    changed_files=[".github/workflows/ci.yml"],
                    dependency_names=["actions/checkout"],
                    changed_patch=(
                        "-      - uses: actions/checkout@"
                        "11d5960a326750d5838078e36cf38b85af677262 # v4\n"
                        "+      - uses: actions/checkout@"
                        "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7"
                    ),
                )
                self.assertEqual(result["decision"], "auto_merge")

    def test_requires_manual_review_for_github_actions_major(self):
        result = self.classify(
            ecosystem="github-actions",
            dependency_type="direct:production",
            update_type="version-update:semver-major",
            changed_files=[".github/workflows/ci.yml"],
            dependency_names=["actions/checkout"],
            changed_patch=(
                "+      - uses: actions/checkout@"
                "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7"
            ),
        )

        self.assertEqual(result["decision"], "manual")
        self.assertIn("major", result["reason"])

    def test_requires_manual_review_when_action_touches_non_workflow_file(self):
        result = self.classify(
            ecosystem="github-actions",
            dependency_type="direct:production",
            changed_files=[
                ".github/workflows/ci.yml",
                "tools/check_dependency_freshness.py",
            ],
            dependency_names=["actions/checkout"],
            changed_patch=(
                "+      - uses: actions/checkout@"
                "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7"
            ),
        )

        self.assertEqual(result["decision"], "manual")
        self.assertIn("檔案範圍", result["reason"])

    def test_requires_manual_review_for_privileged_or_mutable_action(self):
        privileged = self.classify(
            ecosystem="github-actions",
            dependency_type="direct:production",
            changed_files=[".github/workflows/dependabot-merge.yml"],
            dependency_names=["actions/checkout"],
            changed_patch=(
                "+      - uses: actions/checkout@"
                "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7"
            ),
        )
        mutable = self.classify(
            ecosystem="github-actions",
            dependency_type="direct:production",
            changed_files=[".github/workflows/ci.yml"],
            dependency_names=["actions/checkout"],
            changed_patch="+      - uses: actions/checkout@v7",
        )
        extra_command = self.classify(
            ecosystem="github-actions",
            dependency_type="direct:production",
            changed_files=[".github/workflows/ci.yml"],
            dependency_names=["actions/checkout"],
            changed_patch=(
                "-      - uses: actions/checkout@"
                "11d5960a326750d5838078e36cf38b85af677262\n"
                "+      - uses: actions/checkout@"
                "3d3c42e5aac5ba805825da76410c181273ba90b1\n"
                "+      - run: curl https://example.invalid"
            ),
        )
        mismatched_action = self.classify(
            ecosystem="github-actions",
            dependency_type="direct:production",
            changed_files=[".github/workflows/ci.yml"],
            dependency_names=["actions/checkout"],
            changed_patch=(
                "-      - uses: actions/checkout@"
                "11d5960a326750d5838078e36cf38b85af677262\n"
                "+      - uses: actions/setup-python@"
                "5fda3b95a4ea91299a34e894583c3862153e4b97"
            ),
        )

        self.assertEqual(privileged["decision"], "manual")
        self.assertEqual(mutable["decision"], "manual")
        self.assertEqual(extra_command["decision"], "manual")
        self.assertEqual(mismatched_action["decision"], "manual")

    def test_requires_manual_review_for_mixed_or_unknown_metadata(self):
        mixed = self.classify(dependency_names=["packaging", "httpx"])
        unknown = self.classify(
            ecosystem="pip",
            dependency_type="indirect",
            changed_files=[],
            dependency_names=[],
        )

        self.assertEqual(mixed["decision"], "manual")
        self.assertEqual(unknown["decision"], "manual")

    def test_requires_manual_review_for_unknown_ecosystem(self):
        result = self.classify(ecosystem="docker")

        self.assertEqual(result["decision"], "manual")

    def test_writes_github_output_and_cli_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "github-output.txt"
            result = self.classify()
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}):
                policy.write_github_output(result)

            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "classify_dependabot_update.py",
                        "--ecosystem",
                        "github-actions",
                        "--dependency-type",
                        "direct:production",
                        "--update-type",
                        "version-update:semver-major",
                        "--dependency-names",
                        "actions/checkout",
                        "--changed-file",
                        ".github/workflows/ci.yml",
                        "--patch-file",
                        str(Path(tmp) / "change.patch"),
                    ],
                ),
                patch("builtins.print") as print_result,
            ):
                patch_path = Path(tmp) / "change.patch"
                patch_path.write_text(
                    "-      - uses: actions/checkout@"
                    "11d5960a326750d5838078e36cf38b85af677262 # v4\n"
                    "+      - uses: actions/checkout@"
                    "3d3c42e5aac5ba805825da76410c181273ba90b1 # v7",
                    encoding="utf-8",
                )
                exit_code = policy.main()

            output = output_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("decision=auto_merge", output)
        self.assertIn("label=dependencies-auto-merge", output)
        print_result.assert_called_once()


if __name__ == "__main__":
    unittest.main()
