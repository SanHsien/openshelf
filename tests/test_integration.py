"""整合測試：以 httpx.MockTransport 模擬 SyncUserLibrary，驗證分頁與分類。

不連網、不需登入態：用假的後端回應驗證 list_library 的分頁聚合、去重、
停止條件，以及三態分類（drm_free / acsm / no_export）能正確解析。
"""

import json
import unittest

import httpx

from openshelf.classify import classify
from openshelf.playbooks import check_library_endpoint, list_library

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

    def test_stops_without_token(self):
        single = [[_book("A", "書A", _DRM_FREE)], [99], None]

        def handler(request):
            return httpx.Response(200, json=single)

        with self._client(handler) as client:
            books = list_library(client)
        self.assertEqual([b.volume_id for b in books], ["A"])


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


if __name__ == "__main__":
    unittest.main()
