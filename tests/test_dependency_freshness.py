"""依賴新鮮度工具：pyproject 解析、版本比較與報告輸出。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_dependency_freshness as freshness


class DependencyParsingTest(unittest.TestCase):
    def test_loads_runtime_optional_and_build_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            pyproject = Path(tmp) / "pyproject.toml"
            pyproject.write_text(
                """
[project]
dependencies = ["httpx>=0.27", "click>=8.1"]

[project.optional-dependencies]
gui = ["PySide6>=6.6"]
build = ["pyinstaller>=6.6"]

[build-system]
requires = ["setuptools>=77", "wheel"]
build-backend = "setuptools.build_meta"
""".strip(),
                encoding="utf-8",
            )

            packages = freshness.load_direct_dependencies(pyproject)

        by_name = {freshness.normalize_package_name(row["name"]): row for row in packages}
        self.assertEqual(by_name["httpx"]["minimum"], "0.27")
        self.assertEqual(by_name["httpx"]["group"], "runtime")
        self.assertEqual(by_name["pyside6"]["group"], "optional:gui")
        self.assertEqual(by_name["pyinstaller"]["group"], "optional:build")
        self.assertEqual(by_name["setuptools"]["group"], "build-system")
        self.assertEqual(by_name["wheel"]["minimum"], "")

    def test_version_comparison_follows_pep_440(self):
        self.assertFalse(freshness.is_newer_version("1.14", "1.14.0"))
        self.assertTrue(freshness.is_newer_version("1.14.1", "1.14"))
        self.assertTrue(freshness.is_newer_version("6.10.1", "6.6"))
        self.assertTrue(freshness.is_newer_version("1.0", "1.0rc1"))
        self.assertTrue(freshness.is_newer_version("1.0.post1", "1.0"))
        self.assertFalse(freshness.is_newer_version("2.0", "1!1.0"))


class DependencyStatusTest(unittest.TestCase):
    def test_collect_status_marks_outdated_and_unversioned_requirements(self):
        packages = [
            {
                "name": "httpx",
                "minimum": "0.27",
                "requirement": "httpx>=0.27",
                "group": "runtime",
            },
            {
                "name": "wheel",
                "minimum": "",
                "requirement": "wheel",
                "group": "build-system",
            },
        ]

        with patch.object(
            freshness,
            "fetch_pypi_version",
            side_effect=lambda name, timeout=10.0: {
                "httpx": "0.28.1",
                "wheel": "0.46.1",
            }[name],
        ):
            rows = freshness.collect_status(packages)

        self.assertTrue(rows[0]["outdated"])
        self.assertFalse(rows[0]["check_failed"])
        self.assertFalse(rows[1]["outdated"])
        self.assertTrue(rows[1]["check_failed"])

    def test_report_and_github_output_include_attention_state(self):
        rows = [
            {
                "name": "httpx",
                "minimum": "0.27",
                "requirement": "httpx>=0.27",
                "group": "runtime",
                "latest": "0.28.1",
                "outdated": True,
                "check_failed": False,
            }
        ]
        report = freshness.render_markdown(rows)
        self.assertIn("OpenShelf 依賴新鮮度檢查", report)
        self.assertIn("需要維護", report)
        self.assertIn("guarded auto-merge", report)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output.txt"
            report_path = Path(tmp) / "report.md"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                freshness.write_github_output(
                    outdated=True,
                    check_failed=False,
                    report_path=report_path,
                )
            content = output.read_text(encoding="utf-8")

        self.assertIn("needs_attention=true", content)
        self.assertIn(f"report_path={report_path.as_posix()}", content)


if __name__ == "__main__":
    unittest.main()
