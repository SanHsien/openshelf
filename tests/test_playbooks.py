"""playbooks：回應解析、SAPISIDHASH、cookie 取值。"""

import re
import unittest

import httpx

from openshelf.classify import classify
from openshelf.playbooks import (
    _PAGE_SIZE,
    _extract_meta,
    _find_cover_url,
    _get_sapisid,
    _library_body,
    _parse_download_block,
    _parse_library,
    _sapisidhash,
    cover_thumb_url,
)

# 取自實際 SyncUserLibrary 回應的下載區塊樣本
_BLOCK_DRM_FREE = [3, None, 2, None, [None, 0], None, 1, None, None,
                   [[[2, "https://books.google.com/books/download/x.pdf?id=A&output=pdf&source=gbs_api"],
                     [1, "https://books.google.com/books/download/x.epub?id=A&output=epub&source=gbs_api"]]]]
_BLOCK_ACSM = [3, None, 2, None, [None, 0], None, 2, None, None,
               [[[1, None, "https://books.google.com/books/download/x-epub.acsm?id=A&format=epub&output=acs4_fulfillment_token&source=gbs_api"]]]]
_BLOCK_NONE = [3, None, 2, None, [None, 0], None, 2]


def _book(volume_id, title, authors, block):
    info = [title, authors, "pub", "2020-01-01", "desc", 100, "v",
            [["cover", 1, "#000", 1, 1]], "zh", "store"]
    return [volume_id, info, [None, "1"], None, block]


class ParseDownloadBlock(unittest.TestCase):
    def test_drm_free_direct(self):
        opts = _parse_download_block(_BLOCK_DRM_FREE)
        fmts = {o.fmt for o in opts}
        self.assertEqual(fmts, {"pdf", "epub"})
        self.assertTrue(all(o.url.startswith("https://") for o in opts))

    def test_acsm(self):
        opts = _parse_download_block(_BLOCK_ACSM)
        self.assertEqual([o.fmt for o in opts], ["acsm"])
        self.assertIn("acs4_fulfillment_token", opts[0].url)

    def test_no_export(self):
        self.assertEqual(_parse_download_block(_BLOCK_NONE), [])

    def test_garbage(self):
        self.assertEqual(_parse_download_block(None), [])
        self.assertEqual(_parse_download_block([]), [])


class ParseLibrary(unittest.TestCase):
    def test_three_categories(self):
        raw = [[
            _book("A", "無DRM書", ["作者甲"], _BLOCK_DRM_FREE),
            _book("B", "DRM書", ["作者乙", "作者丙"], _BLOCK_ACSM),
            _book("C", "試閱本", ["作者丁"], _BLOCK_NONE),
        ]]
        books = _parse_library(raw)
        self.assertEqual(len(books), 3)
        self.assertEqual(books[0].title, "無DRM書")
        self.assertEqual(books[0].publisher, "pub")
        self.assertEqual(books[0].published, "2020-01-01")
        self.assertEqual(books[1].author, "作者乙, 作者丙")
        self.assertEqual(classify(books[0].export_options), "drm_free")
        self.assertEqual(classify(books[1].export_options), "acsm")
        self.assertEqual(classify(books[2].export_options), "no_export")

    def test_empty_and_garbage(self):
        self.assertEqual(_parse_library([]), [])
        self.assertEqual(_parse_library([None]), [])
        self.assertEqual(_parse_library([[["A"]]]), [])  # 缺 info


class Cover(unittest.TestCase):
    def test_thumb_url_from_volume_id(self):
        url = cover_thumb_url("ABC123")
        self.assertIn("ABC123", url)
        self.assertIn("frontcover", url)
        self.assertTrue(url.startswith("https://"))

    def test_find_cover_in_nested_info(self):
        info = ["書名", ["作者"], "pub", "2020",
                ["x", "https://books.google.com/books/content?id=A&printsec=frontcover&img=1"]]
        self.assertIn("frontcover", _find_cover_url(info))

    def test_find_cover_ignores_download_url(self):
        info = ["書名", ["作者"],
                "https://books.google.com/books/download/x.epub?id=A&output=epub"]
        self.assertEqual(_find_cover_url(info), "")

    def test_find_cover_none(self):
        self.assertEqual(_find_cover_url(["書名", ["作者"], "pub"]), "")

    def test_parse_library_captures_cover(self):
        info = ["有封面書", ["作者"], "pub", "2020",
                "https://books.google.com/books/content?id=Z&printsec=frontcover"]
        raw = [[["Z", info, [None, "1"], None, _BLOCK_DRM_FREE]]]
        books = _parse_library(raw)
        self.assertEqual(len(books), 1)
        self.assertIn("frontcover", books[0].cover_url)


class Pagination(unittest.TestCase):
    def test_library_body(self):
        b0 = _library_body(None)
        self.assertEqual(b0[4], [_PAGE_SIZE])
        self.assertEqual(b0[8], [None, 1])
        b1 = _library_body("TOKEN")
        self.assertEqual(b1[8], ["TOKEN", 1])

    def test_extract_meta(self):
        raw = [["book"], None, None, [228], ["x" * 30], None]
        total, token = _extract_meta(raw)
        self.assertEqual(total, 228)
        self.assertEqual(token, "x" * 30)

    def test_extract_meta_single_page(self):
        # 沒有 token（短字串不算）→ None
        total, token = _extract_meta([["book"], [12]])
        self.assertEqual(total, 12)
        self.assertIsNone(token)


class Sapisidhash(unittest.TestCase):
    def test_format(self):
        auth = _sapisidhash("MY_SAPISID", origin="https://play.google.com")
        # 形如：SAPISIDHASH ts_hash SAPISID1PHASH ts_hash SAPISID3PHASH ts_hash
        parts = auth.split(" ")
        self.assertEqual(parts[0], "SAPISIDHASH")
        self.assertEqual(parts[2], "SAPISID1PHASH")
        self.assertEqual(parts[4], "SAPISID3PHASH")
        for token in (parts[1], parts[3], parts[5]):
            ts, _, digest = token.partition("_")
            self.assertTrue(ts.isdigit())
            self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", digest))

    def test_get_sapisid_with_duplicate_cookies(self):
        # 同名 SAPISID 存在多個網域（值相同）不應拋 CookieConflict
        jar = httpx.Cookies()
        jar.set("SAPISID", "VALUE123", domain="google.com")
        jar.set("SAPISID", "VALUE123", domain="play.google.com")
        with httpx.Client(cookies=jar) as client:
            self.assertEqual(_get_sapisid(client), "VALUE123")


if __name__ == "__main__":
    unittest.main()
