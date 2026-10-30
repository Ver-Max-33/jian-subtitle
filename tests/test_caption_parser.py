import unittest

from subtitle_app.caption_parser import CaptionParser


class CaptionParserTests(unittest.TestCase):
    def test_normal_spaces_remain_inside_one_caption(self):
        captions = CaptionParser().parse("Hello world 你好 世界")

        self.assertEqual(("Hello world 你好 世界",), captions)

    def test_balanced_corner_brackets_create_multiple_captions(self):
        captions = CaptionParser().parse("【你终于来了】【我等了很久】")

        self.assertEqual(("你终于来了", "我等了很久"), captions)

    def test_hash_in_filename_text_becomes_an_explicit_line_break(self):
        captions = CaptionParser().parse("第一行#第二行")

        self.assertEqual(("第一行\n第二行",), captions)

    def test_unbalanced_corner_brackets_are_flagged_for_review(self):
        parser = CaptionParser()

        self.assertTrue(parser.requires_review("【开头没有结尾"))
        self.assertTrue(parser.requires_review("有结尾没有开头】"))
        self.assertFalse(parser.requires_review("【完整一条】【完整两条】"))


if __name__ == "__main__":
    unittest.main()
