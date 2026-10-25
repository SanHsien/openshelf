"""檔名安全：Windows 保留名、控制字元、辨識字串碰撞。"""

import unittest

import httpx

from openshelf import service
from openshelf.export import safe_filename
from openshelf.manifest import BookEntry, Manifest
from openshelf.playbooks import ExportOption
from tests.test_service_flow import EPUB, _Env


class WindowsSafeNames(unittest.TestCase):
    def test_reserved_device_names_are_not_used_as_stem(self):
        # Windows 上 CON.epub / NUL.epub / com1.pdf 都是裝置名，無法建立檔案
        for title in ("CON", "nul", "Aux", "PRN", "COM1", "lpt9"):
            stem = safe_filename(title, "", "epub")[: -len(".epub")]
            self.assertNotIn(stem.split(".")[0].upper(), {
                "CON", "PRN", "AUX", "NUL", "COM1", "LPT9",
            }, title)

    def test_reserved_name_with_author_is_fine(self):
        self.assertEqual(safe_filename("CON", "作者", "epub"), "CON - 作者.epub")

    def test_control_characters_removed(self):
        name = safe_filename("a\x00b\x1fc", "x\x07", "epub")
        self.assertFalse(any(ord(ch) < 32 for ch in name))

    def test_dots_only_title_does_not_become_hidden_file(self):
        self.assertEqual(safe_filename("...", "", "epub"), "untitled.epub")
        self.assertEqual(safe_filename(" . ", "", "pdf"), "untitled.pdf")


class DisambiguatorCollisions(_Env):
    def _run(self, books):
        m = Manifest(self.out / "manifest.json")
        cache = {}
        for vid, pub in books:
            m.upsert(BookEntry(volume_id=vid, title="同名", author="作者",
                               publisher=pub, published="2020-01-01"))
            cache[vid] = [ExportOption(fmt="epub", url=f"https://x/{vid}")]
        m.save()
        self._patch_client(lambda req: httpx.Response(200, content=EPUB))
        res = service.export(self.cfg, "epub", True, option_cache=cache, log=lambda s: None)
        loaded = Manifest.load(self.out / "manifest.json")
        paths = {loaded.get(v).file_path.casefold() for v, _ in books}
        return res, paths

    def test_publishers_differing_only_by_illegal_chars_do_not_overwrite(self):
        res, paths = self._run([("A", "X:Y"), ("B", "X?Y")])
        self.assertEqual(res.done, 2)
        self.assertEqual(len(paths), 2)

    def test_publishers_differing_only_by_case_do_not_overwrite(self):
        res, paths = self._run([("A", "Press"), ("B", "PRESS")])
        self.assertEqual(len(paths), 2)

    def test_long_shared_publisher_does_not_drop_volume_id(self):
        pub = "出版社" * 40
        res, paths = self._run([("A", pub), ("B", pub)])
        self.assertEqual(len(paths), 2)
