import tempfile
import unittest
from pathlib import Path

from PIL import Image

from subtitle_app.import_service import ImportService
from subtitle_app.models import CaptionStatus, SubtitleSource
from subtitle_app.source_relocator import SourceRelocator


class SourceRelocatorTests(unittest.TestCase):
    def test_missing_source_can_be_relocated_without_losing_manual_caption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_dir = root / "old"
            new_dir = root / "new"
            old_dir.mkdir()
            new_dir.mkdir()
            old_path = old_dir / "原字幕.png"
            Image.new("RGB", (40, 30), "white").save(old_path)
            asset = ImportService().import_paths([old_path]).assets[0]
            asset.subtitles[0].text = "人工校对内容"
            asset.subtitles[0].source = SubtitleSource.MANUAL
            new_path = new_dir / old_path.name
            old_path.replace(new_path)
            relocator = SourceRelocator()

            relocator.mark_missing([asset])
            result = relocator.relocate([asset], new_dir)

        self.assertEqual(1, result.relocated_count)
        self.assertEqual(new_path.resolve(), asset.source_path)
        self.assertEqual(CaptionStatus.READY, asset.caption_status)
        self.assertEqual("人工校对内容", asset.subtitles[0].text)

    def test_ambiguous_duplicate_filename_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "old" / "同名字幕.png"
            source.parent.mkdir()
            Image.new("RGB", (40, 30), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]
            source.unlink()
            for folder in (root / "new" / "a", root / "new" / "b"):
                folder.mkdir(parents=True)
                Image.new("RGB", (40, 30), "white").save(folder / source.name)
            relocator = SourceRelocator()
            relocator.mark_missing([asset])

            result = relocator.relocate([asset], root / "new", recursive=True)

        self.assertEqual(0, result.relocated_count)
        self.assertEqual(1, result.ambiguous_count)
        self.assertEqual(CaptionStatus.UNREADABLE, asset.caption_status)


if __name__ == "__main__":
    unittest.main()
