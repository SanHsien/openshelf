"""update：版本解析與比較（不連網）。"""

import unittest

from openshelf.update import is_newer, parse_version, tag_from_release_json


class ParseVersion(unittest.TestCase):
    def test_with_v_prefix(self):
        self.assertEqual(parse_version("v0.4.0"), (0, 4, 0))

    def test_plain(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_two_parts(self):
        self.assertEqual(parse_version("v2.1"), (2, 1))

    def test_garbage(self):
        self.assertEqual(parse_version(""), ())
        self.assertEqual(parse_version("vNext"), ())


class IsNewer(unittest.TestCase):
    def test_newer_patch(self):
        self.assertTrue(is_newer("v0.4.1", "0.4.0"))

    def test_newer_minor(self):
        self.assertTrue(is_newer("v0.5.0", "0.4.9"))

    def test_same(self):
        self.assertFalse(is_newer("v0.4.0", "0.4.0"))

    def test_older(self):
        self.assertFalse(is_newer("v0.3.9", "0.4.0"))

    def test_padding(self):
        self.assertFalse(is_newer("v0.4", "0.4.0"))
        self.assertTrue(is_newer("v0.4.1", "0.4"))

    def test_invalid_latest(self):
        self.assertFalse(is_newer("", "0.4.0"))


class TagFromJson(unittest.TestCase):
    def test_dict(self):
        self.assertEqual(tag_from_release_json({"tag_name": "v0.4.0"}), "v0.4.0")

    def test_missing(self):
        self.assertEqual(tag_from_release_json({}), "")
        self.assertEqual(tag_from_release_json(None), "")


if __name__ == "__main__":
    unittest.main()
