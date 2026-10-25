"""下載失敗後不留 .part 半成品。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from openshelf import export as export_mod
from openshelf.playbooks import ExportOption


class PartFileCleanup(unittest.TestCase):
    def test_non_http_error_does_not_leave_part_file(self):
        out = Path(tempfile.mkdtemp())

        def boom(client, url, dest):
            Path(dest).write_bytes(b"partial")
            raise OSError("disk full")

        with mock.patch.object(export_mod, "download", boom):
            with self.assertRaises(OSError):
                export_mod.download_option(
                    httpx.Client(), ExportOption(fmt="epub", url="https://x/a"),
                    out, "書", "作者", retries=1,
                )
        self.assertEqual(list(out.glob("*.part")), [])
