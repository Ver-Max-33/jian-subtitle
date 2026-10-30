import tempfile
import unittest
from pathlib import Path

from PIL import Image

from subtitle_app.models import CaptionStatus, SubtitleSource
from subtitle_app.import_service import ImportService


class ImportServiceTests(unittest.TestCase):
    def test_importing_a_chinese_named_file_populates_metadata_and_caption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "你好 世界.png"
            Image.new("RGB", (20, 20), "white").save(path)

            result = ImportService().import_paths([path])

        self.assertEqual(1, len(result.assets))
        asset = result.assets[0]
        self.assertEqual("你好 世界.png", asset.filename)
        self.assertIsNotNone(asset.created_at)
        self.assertEqual(CaptionStatus.READY, asset.caption_status)
        self.assertEqual("你好 世界", asset.subtitles[0].text)
        self.assertEqual(SubtitleSource.FILENAME_AUTO, asset.subtitles[0].source)

    def test_importing_a_timestamp_named_file_keeps_the_caption_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "20260121_021602.png"
            Image.new("RGB", (20, 20), "white").save(path)

            result = ImportService().import_paths([path])

        asset = result.assets[0]
        self.assertEqual(CaptionStatus.MISSING, asset.caption_status)
        self.assertEqual([], asset.subtitles)

    def test_importing_the_same_canonical_path_twice_only_adds_it_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "唯一字幕.png"
            Image.new("RGB", (20, 20), "white").save(path)

            result = ImportService().import_paths([path, path])

        self.assertEqual(1, len(result.assets))

    def test_corrupted_image_is_kept_visible_but_marked_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "损坏图片.png"
            path.write_bytes(b"not an image")

            result = ImportService().import_paths([path])

        asset = result.assets[0]
        self.assertEqual(CaptionStatus.UNREADABLE, asset.caption_status)
        self.assertEqual([], asset.subtitles)

    def test_unsupported_file_is_reported_without_entering_the_asset_list(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "说明.txt"
            path.write_text("not an image", encoding="utf-8")

            result = ImportService().import_paths([path])

        self.assertEqual([], result.assets)
        self.assertEqual("IMPORT_UNSUPPORTED_FORMAT", result.issues[0].code)

    def test_missing_source_is_reported_instead_of_crashing_the_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "已经被删除.png"

            result = ImportService().import_paths([path])

        self.assertEqual([], result.assets)
        self.assertEqual("SOURCE_MISSING", result.issues[0].code)

    def test_unbalanced_multicaption_filename_is_kept_but_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "【需要确认.png"
            Image.new("RGB", (20, 20), "white").save(path)

            result = ImportService().import_paths([path])

        self.assertEqual(CaptionStatus.NEEDS_REVIEW, result.assets[0].caption_status)
        self.assertEqual("【需要确认", result.assets[0].subtitles[0].text)

    def test_reclassification_does_not_overwrite_manual_text_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "文件名字幕.png"
            Image.new("RGB", (20, 20), "white").save(path)
            service = ImportService()
            asset = service.import_paths([path]).assets[0]
            asset.subtitles[0].text = "用户修改"
            asset.subtitles[0].source = SubtitleSource.MANUAL

            changed = service.reclassify_asset(asset)

        self.assertFalse(changed)
        self.assertEqual("用户修改", asset.subtitles[0].text)

    def test_reclassification_can_restore_filename_caption_when_not_manual(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "文件名字幕.png"
            Image.new("RGB", (20, 20), "white").save(path)
            service = ImportService()
            asset = service.import_paths([path]).assets[0]
            asset.subtitles.clear()
            asset.caption_status = CaptionStatus.MISSING

            changed = service.reclassify_asset(asset)

        self.assertTrue(changed)
        self.assertEqual("文件名字幕", asset.subtitles[0].text)


if __name__ == "__main__":
    unittest.main()
