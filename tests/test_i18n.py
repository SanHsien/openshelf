"""i18n：語言偵測與轉譯後援（不需 Qt）。"""

import unittest

from openshelf.ui import i18n


class DetectDefault(unittest.TestCase):
    def test_qlocale_style_names(self):
        self.assertEqual(i18n.detect_default("zh_TW"), "zh")
        self.assertEqual(i18n.detect_default("zh_CN"), "zh")
        self.assertEqual(i18n.detect_default("en_US"), "en")
        self.assertEqual(i18n.detect_default("ja_JP"), "en")

    def test_windows_getlocale_style_name(self):
        # Windows 的 locale.getlocale() 會回這種格式，不是 zh_TW
        self.assertEqual(i18n.detect_default("Chinese (Traditional)_Taiwan"), "zh")

    def test_empty_falls_back_without_error(self):
        # 無提示時走 stdlib 後援，不得丟例外、回傳值必為合法語言
        self.assertIn(i18n.detect_default(""), i18n.LANGUAGES)


class Translate(unittest.TestCase):
    def setUp(self):
        self._orig = i18n.current_language()

    def tearDown(self):
        i18n.set_language(self._orig)

    def test_zh_passthrough(self):
        i18n.set_language("zh")
        self.assertEqual(i18n.tr("登入"), "登入")

    def test_en_lookup_and_fallback(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr("登入"), "Sign in")
        self.assertEqual(i18n.tr("ACSM 逾時"), "stale ACSM")
        # 查不到的字串回原文，不會缺字
        self.assertEqual(i18n.tr("沒有這個字串"), "沒有這個字串")

    def test_invalid_language_falls_back_to_zh(self):
        i18n.set_language("fr")
        self.assertEqual(i18n.current_language(), "zh")


if __name__ == "__main__":
    unittest.main()
