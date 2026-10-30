import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from subtitle_app.import_service import ImportService
from subtitle_app.models import ExportOptions
from subtitle_app.output_preflight import OutputPreflight


class OutputPreflightTests(unittest.TestCase):
    def test_missing_source_is_a_blocking_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "稍后删除.png"
            Image.new("RGB", (20, 20), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]
            source.unlink()

            result = OutputPreflight().inspect(
                [asset], ExportOptions(output_dir=root / "output")
            )

        self.assertTrue(any("源文件不存在" in error for error in result.errors))

    def test_unwritable_destination_is_a_blocking_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "字幕.png"
            Image.new("RGB", (20, 20), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]

            with patch("subtitle_app.output_preflight.os.access", return_value=False):
                result = OutputPreflight().inspect(
                    [asset], ExportOptions(output_dir=root / "output")
                )

        self.assertTrue(any("无法写入" in error for error in result.errors))

    def test_output_nested_inside_source_folder_is_a_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "字幕.png"
            Image.new("RGB", (20, 20), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]

            result = OutputPreflight().inspect(
                [asset], ExportOptions(output_dir=root / "generated" / "output")
            )

        self.assertTrue(any("源图片文件夹内部" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
