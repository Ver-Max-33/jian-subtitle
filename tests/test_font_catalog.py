import unittest
from pathlib import Path

from subtitle_app.font_catalog import FontCatalog


class FontCatalogTests(unittest.TestCase):
    def test_installed_font_family_resolves_to_a_real_file(self):
        expected_family = "Arial" if Path("/System/Library/Fonts").exists() else "Segoe UI"

        resolved = FontCatalog().find_path(expected_family)

        if resolved is None:
            self.skipTest(f"当前系统没有 {expected_family}")
        self.assertTrue(resolved.is_file())


class ChineseFontNameTests(unittest.TestCase):
    def test_prefers_simplified_chinese_family_name(self):
        from types import SimpleNamespace as Record
        from subtitle_app.web_fonts import _chinese_name

        def name(name_id, platform, language, text):
            return Record(nameID=name_id, platformID=platform, langID=language, toUnicode=lambda: text)
        names = Record(names=[name(1, 3, 0x409, "SimHei"), name(1, 3, 0x404, "黑體"), name(1, 3, 0x804, "黑体")])
        self.assertEqual("黑体", _chinese_name(names))
        self.assertIsNone(_chinese_name(Record(names=[name(1, 3, 0x409, "Arial")])))


if __name__ == "__main__":
    unittest.main()
