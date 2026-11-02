from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import json
import sys

from click.testing import CliRunner
from openshelf import cli

from openshelf.session import check_storage_permissions


class WindowsStoragePermissionsTest(unittest.TestCase):
    def check(self, rules=(), null_dacl=False, error=None):
        data = {"currentUser": "S-1-5-21-123", "nullDacl": null_dacl, "rules": list(rules)}
        result = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "storage_state.json"
            path.write_text("{}", encoding="utf-8")
            with mock.patch("openshelf.session.sys.platform", "win32"), mock.patch(
                "subprocess.run", return_value=result, side_effect=error,
                create=True,
            ):
                return check_storage_permissions(path)

    @staticmethod
    def rule(sid, rights=1, kind=0, inherit_only=False):
        return {"sid": sid, "rights": rights, "type": kind, "inheritOnly": inherit_only}

    def test_private_acl(self):
        self.assertIsNone(self.check([self.rule(s) for s in (
            "S-1-5-21-123", "S-1-5-18", "S-1-5-32-544",
        )]))

    def test_other_readers_warn(self):
        for sid in ("S-1-1-0", "S-1-5-11", "S-1-5-32-545", "S-1-5-21-999"):
            for rights in (1, 1179785, 2032127, -2147483648, 268435456):
                with self.subTest(sid=sid, rights=rights):
                    self.assertIn("ACL", self.check([self.rule(sid, rights)]))

    def test_non_read_and_inherit_only_rules(self):
        self.assertIsNone(self.check([
            self.rule("S-1-1-0", rights=2),
            self.rule("S-1-1-0", kind=1),
            self.rule("S-1-1-0", inherit_only=True),
        ]))

    def test_null_dacl_warns(self):
        self.assertIn("ACL", self.check(null_dacl=True))

    def test_query_failures_warn(self):
        for error in (OSError("unavailable"), subprocess.TimeoutExpired("powershell", 10)):
            with self.subTest(error=type(error).__name__):
                self.assertIn("無法確認", self.check(error=error))

    def test_invalid_query_output_warns(self):
        for result in (
            subprocess.CompletedProcess([], 0, "not json", ""),
            subprocess.CompletedProcess([], 0, "{}", ""),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "storage_state.json"
                path.write_text("{}", encoding="utf-8")
                with mock.patch("openshelf.session.sys.platform", "win32"), mock.patch(
                    "subprocess.run", return_value=result,
                ):
                    self.assertIn("無法確認", check_storage_permissions(path))
        self.assertIn("無法確認", self.check(error=subprocess.CalledProcessError(1, "powershell")))

    @unittest.skipUnless(sys.platform == "win32", "Windows ACL 實機測試")
    def test_real_windows_acl(self):
        # 只使用空白測試檔，不接觸真正登入態；同時驗證中文、單引號與括號路徑。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "登入 ' [test].json"
            path.write_text("{}", encoding="utf-8")
            identity = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
                capture_output=True, text=True, check=True, timeout=10,
            ).stdout.strip()
            subprocess.run(["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"*{identity}:F"],
                           check=True, capture_output=True, timeout=10)
            self.assertIsNone(check_storage_permissions(path))
            subprocess.run(["icacls.exe", str(path), "/grant", "*S-1-1-0:R"],
                           check=True, capture_output=True, timeout=10)
            self.assertIn("ACL 可能過寬", check_storage_permissions(path))

    def test_doctor_warns_for_windows_acl(self):
        data = {"currentUser": "S-1-5-21-123", "nullDacl": False,
                "rules": [self.rule("S-1-1-0")]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "storage_state.json"
            path.write_text("{}", encoding="utf-8")
            config = Path(tmp) / "config.toml"
            config.write_text(f'storage_state = "{path.as_posix()}"\n', encoding="utf-8")
            with mock.patch("openshelf.session.sys.platform", "win32"), mock.patch(
                "subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(data), ""),
            ), mock.patch("openshelf.cli.build_client"), mock.patch(
                "openshelf.playbooks.check_library_endpoint", return_value=(True, "端點正常"),
            ):
                result = CliRunner().invoke(cli.main, ["--config", str(config), "doctor"])
            self.assertEqual(result.exit_code, 0, result.output)
            # click wraps the warning at the terminal width, and a long temp path can push a line
            # break between words (seen on the Linux runner); compare with whitespace collapsed.
            output = " ".join(result.output.split())
            self.assertIn("ACL 可能過寬", output)
            self.assertIn("OK 端點正常", output)
