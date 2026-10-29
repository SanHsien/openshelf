"""整合測試：以 httpx.MockTransport 模擬 SyncUserLibrary，驗證分頁與分類。

不連網、不需登入態：用假的後端回應驗證 list_library 的分頁聚合、去重、
停止條件，以及三態分類（drm_free / acsm / no_export）能正確解析。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx
from click.testing import CliRunner

from openshelf import cli
from openshelf.session import check_storage_permissions

from openshelf.classify import classify
from openshelf.playbooks import (
    IncompleteLibrary,
    _parse_library,
    check_library_endpoint,
    list_library,
)

# 下載區塊樣本（block[9] 內含可下載格式）
_DRM_FREE = [3, None, 2, None, [None, 0], None, 1, None, None,
             [[[1, "https://books.google.com/books/download/x.epub?id=A&output=epub"]]]]
_ACSM = [3, None, 2, None, [None, 0], None, 2, None, None,
         [[[1, None, "https://books.google.com/books/download/x.acsm?id=B&output=acs4_fulfillment_token"]]]]
_NONE = [3, None, 2, None, [None, 0], None, 2]


def _book(vid, title, block, cover=None):
    info = [title, ["作者"], "出版社", "2020-01-01"]
    if cover:
        info.append(cover)
    return [vid, info, [None, "1"], None, block]


def _token_of(request: httpx.Request):
    body = json.loads(request.content)
    slot = body[8]
    return slot[0] if isinstance(slot, list) and slot and slot[0] else None


class ListLibraryPaging(unittest.TestCase):
    def _client(self, handler):
        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        client.cookies.set("SAPISID", "DUMMY", domain="google.com")
        return client

    def test_two_pages_aggregate_and_classify(self):
        page1 = [
            [
                _book("A", "無DRM書", _DRM_FREE,
                      cover="https://books.google.com/books/content?id=A&printsec=frontcover"),
                _book("B", "DRM書", _ACSM),
            ],
            [3],            # total
            ["t" * 30],     # 分頁游標
        ]
        page2 = [
            [_book("C", "試閱本", _NONE)],
            [3],
            None,           # 沒有下一頁游標
        ]

        def handler(request):
            token = _token_of(request)
            raw = page1 if token is None else page2
            return httpx.Response(200, json=raw)

        with self._client(handler) as client:
            books = list_library(client)

        self.assertEqual([b.volume_id for b in books], ["A", "B", "C"])
        self.assertEqual(classify(books[0].export_options), "drm_free")
        self.assertEqual(classify(books[1].export_options), "acsm")
        self.assertEqual(classify(books[2].export_options), "no_export")
        self.assertIn("frontcover", books[0].cover_url)

    def test_dedup_and_stop_when_total_reached(self):
        # 第二頁重複了 A（不同網域游標），且總數為 2 → 應去重並在取齊後停止
        page1 = [[_book("A", "書A", _DRM_FREE), _book("B", "書B", _DRM_FREE)],
                 [2], ["x" * 30]]
        page2 = [[_book("A", "書A", _DRM_FREE)], [2], ["y" * 30]]
        pages = [page1, page2]
        calls = {"n": 0}

        def handler(request):
            i = min(calls["n"], len(pages) - 1)
            calls["n"] += 1
            return httpx.Response(200, json=pages[i])

        with self._client(handler) as client:
            books = list_library(client)

        self.assertEqual(sorted(b.volume_id for b in books), ["A", "B"])
        self.assertEqual(calls["n"], 1)  # 取齊 total=2 後即停，不再要第二頁

    def test_stops_without_token_when_total_unknown(self):
        single = [[_book("A", "書A", _DRM_FREE)], None, None]

        def handler(request):
            return httpx.Response(200, json=single)

        with self._client(handler) as client:
            books = list_library(client)
        self.assertEqual([b.volume_id for b in books], ["A"])

    def test_incomplete_when_total_larger_and_no_token(self):
        single = [[_book("A", "書A", _DRM_FREE)], [99], None]

        def handler(request):
            return httpx.Response(200, json=single)

        with self._client(handler) as client:
            with self.assertRaises(IncompleteLibrary):
                list_library(client)

    def test_incomplete_when_later_page_drops_total(self):
        page1 = [[_book("A", "書A", _DRM_FREE)], [5], ["t" * 30]]
        page2 = [[_book("B", "書B", _DRM_FREE)], None, None]  # 後頁沒有總數也沒有游標

        def handler(request):
            return httpx.Response(200, json=page1 if _token_of(request) is None else page2)

        with self._client(handler) as client:
            with self.assertRaises(IncompleteLibrary):
                list_library(client)

    def test_incomplete_when_page_limit_reached(self):
        n = {"i": 0}

        def handler(request):
            n["i"] += 1
            body = [[_book(f"V{n['i']}", "書", _DRM_FREE)], [10**6], [f"{n['i']:030d}"]]
            return httpx.Response(200, json=body)

        with self._client(handler) as client:
            with self.assertRaises(IncompleteLibrary):
                list_library(client)


class UnknownFormat(unittest.TestCase):
    def test_unknown_format_code_is_skipped_not_epub(self):
        block = [3, None, 2, None, [None, 0], None, 1, None, None,
                 [[[999, "https://books.google.com/books/download/x.bin?id=A"]]]]
        books = _parse_library([[_book("A", "書A", block)]])
        self.assertEqual(books[0].export_options, [])
        self.assertEqual(classify(books[0].export_options), "no_export")


class EndpointDoctor(unittest.TestCase):
    def _client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        client.cookies.set("SAPISID", "DUMMY", domain="google.com")
        return client

    def test_healthy(self):
        raw = [[_book("A", "書A", _DRM_FREE)], [1], None]
        with self._client(lambda r: httpx.Response(200, json=raw)) as client:
            ok, msg = check_library_endpoint(client)
        self.assertTrue(ok)
        self.assertIn("端點正常", msg)

    def test_shape_changed(self):
        # 書目清單不是陣列 → 視為改版
        raw = ["unexpected", [0]]
        with self._client(lambda r: httpx.Response(200, json=raw)) as client:
            ok, msg = check_library_endpoint(client)
        self.assertFalse(ok)
        self.assertIn("改版", msg)

    def test_http_error(self):
        with self._client(lambda r: httpx.Response(500, json=[])) as client:
            ok, msg = check_library_endpoint(client)
        self.assertFalse(ok)




class StoragePermissionsTest(unittest.TestCase):
    def test_missing_file_returns_none(self):
        missing = Path("non_existent_storage_state.json")
        self.assertIsNone(check_storage_permissions(missing))

    def test_windows_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "storage_state.json"
            p.write_text("{}", encoding="utf-8")
            with mock.patch("sys.platform", "win32"):
                self.assertIsNone(check_storage_permissions(p))

    def test_posix_safe_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "storage_state.json"
            p.write_text("{}", encoding="utf-8")
            with mock.patch("sys.platform", "linux"):
                fake_stat = mock.MagicMock()
                for safe_mode in (0o100600, 0o100400):
                    fake_stat.st_mode = safe_mode
                    with mock.patch.object(Path, "stat", return_value=fake_stat):
                        self.assertIsNone(check_storage_permissions(p))

    def test_posix_permissive_permissions_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "storage_state.json"
            p.write_text("{}", encoding="utf-8")
            with mock.patch("sys.platform", "linux"):
                fake_stat = mock.MagicMock()
                for perm_mode in (0o100644, 0o100664, 0o100666, 0o100777):
                    fake_stat.st_mode = perm_mode
                    with mock.patch.object(Path, "stat", return_value=fake_stat):
                        warn = check_storage_permissions(p)
                        self.assertIsNotNone(warn)
                        self.assertIn("權限過寬", warn)
                        self.assertIn("chmod 600", warn)
                        self.assertIn(str(p), warn)

    def test_doctor_cli_warns_on_permissive_storage_state(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "storage_state.json"
            storage.write_text("{}", encoding="utf-8")
            cfg_path = Path(tmp) / "config.toml"
            cfg_path.write_text(f'storage_state = "{storage.as_posix()}"\n', encoding="utf-8")

            fake_stat = mock.MagicMock()
            fake_stat.st_mode = 0o100644
            with mock.patch("sys.platform", "linux"), \
                 mock.patch.object(Path, "stat", return_value=fake_stat), \
                 mock.patch("openshelf.cli.build_client"), \
                 mock.patch("openshelf.playbooks.check_library_endpoint", return_value=(True, "端點正常")):
                res = runner.invoke(cli.main, ["--config", str(cfg_path), "doctor"])
                self.assertEqual(res.exit_code, 0)
                self.assertIn("警告：", res.output)
                self.assertIn("權限過寬", res.output)
                self.assertIn("OK 端點正常", res.output)

    def test_doctor_cli_no_warning_on_safe_storage_state(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "storage_state.json"
            storage.write_text("{}", encoding="utf-8")
            cfg_path = Path(tmp) / "config.toml"
            cfg_path.write_text(f'storage_state = "{storage.as_posix()}"\n', encoding="utf-8")

            fake_stat = mock.MagicMock()
            fake_stat.st_mode = 0o100600
            with mock.patch("sys.platform", "linux"), \
                 mock.patch.object(Path, "stat", return_value=fake_stat), \
                 mock.patch("openshelf.cli.build_client"), \
                 mock.patch("openshelf.playbooks.check_library_endpoint", return_value=(True, "端點正常")):
                res = runner.invoke(cli.main, ["--config", str(cfg_path), "doctor"])
                self.assertEqual(res.exit_code, 0)
                self.assertNotIn("警告：", res.output)
                self.assertIn("OK 端點正常", res.output)

    def test_doctor_cli_no_warning_on_windows(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp) / "storage_state.json"
            storage.write_text("{}", encoding="utf-8")
            cfg_path = Path(tmp) / "config.toml"
            cfg_path.write_text(f'storage_state = "{storage.as_posix()}"\n', encoding="utf-8")

            with mock.patch("sys.platform", "win32"), \
                 mock.patch("openshelf.cli.build_client"), \
                 mock.patch("openshelf.playbooks.check_library_endpoint", return_value=(True, "端點正常")):
                res = runner.invoke(cli.main, ["--config", str(cfg_path), "doctor"])
                self.assertEqual(res.exit_code, 0)
                self.assertNotIn("警告：", res.output)
                self.assertIn("OK 端點正常", res.output)


if __name__ == "__main__":
    unittest.main()
