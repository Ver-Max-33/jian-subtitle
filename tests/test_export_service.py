import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops

from subtitle_app.export_service import ExportService
from subtitle_app.models import CaptionRenderRequest, StyleSettings


class ExportServiceTests(unittest.TestCase):
    def test_export_refuses_to_overwrite_the_source_image(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            Image.new("RGB", (120, 80), "white").save(source)

            with self.assertRaisesRegex(ValueError, "源图"):
                ExportService().export_image(
                    source,
                    source,
                    [CaptionRenderRequest("Caption")],
                    StyleSettings(font_size=18),
                )

    def test_flushes_through_a_writable_handle(self):
        # Windows fsync (FlushFileBuffers) needs write access; a 0-byte write fails the same way on a read-only handle here.
        real_fsync = os.fsync
        def windows_fsync(descriptor):
            os.write(descriptor, b"")
            real_fsync(descriptor)
        with tempfile.TemporaryDirectory() as directory, mock.patch("subtitle_app.export_service.os.fsync", windows_fsync):
            root = Path(directory)
            Image.new("RGB", (40, 30), "white").save(root / "source.png")
            ExportService().export_image(root / "source.png", root / "result.png", [], StyleSettings())
            ExportService().copy_original(root / "source.png", root / "copy.png")
            self.assertTrue((root / "result.png").is_file() and (root / "copy.png").is_file())

    def test_export_writes_a_complete_rendered_file_and_keeps_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            output = root / "out" / "result.png"
            Image.new("RGB", (240, 140), "white").save(source)
            source_bytes = source.read_bytes()

            written = ExportService().export_image(
                source,
                output,
                [CaptionRenderRequest("Caption", position_ratio=(0.5, 0.7))],
                StyleSettings(font_size=24, text_color=(0, 0, 0, 255)),
            )

            self.assertEqual(output.resolve(), written)
            self.assertEqual(source_bytes, source.read_bytes())
            with Image.open(output) as exported:
                self.assertEqual((240, 140), exported.size)
                reference = Image.new("RGB", exported.size, "white")
                self.assertIsNotNone(
                    ImageChops.difference(exported.convert("RGB"), reference).getbbox()
                )

    def test_export_does_not_silently_replace_an_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            output = root / "result.png"
            Image.new("RGB", (80, 60), "white").save(source)
            output.write_bytes(b"existing output")

            with self.assertRaises(FileExistsError):
                ExportService().export_image(
                    source,
                    output,
                    [CaptionRenderRequest("Caption")],
                    StyleSettings(font_size=16),
                )

            self.assertEqual(b"existing output", output.read_bytes())

    def test_exif_orientation_is_normalized_instead_of_applied_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rotated.jpg"
            output = root / "out" / "rotated.jpg"
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGB", (40, 80), "white").save(source, exif=exif)

            ExportService().export_image(
                source,
                output,
                [CaptionRenderRequest("Caption")],
                StyleSettings(font_size=12, text_color=(0, 0, 0, 255)),
            )

            with Image.open(output) as exported:
                self.assertEqual((80, 40), exported.size)
                self.assertEqual(1, exported.getexif().get(274, 1))

    def test_metadata_can_be_explicitly_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jpg"
            output = root / "out" / "result.jpg"
            exif = Image.Exif()
            exif[270] = "private description"
            Image.new("RGB", (80, 60), "white").save(source, exif=exif)

            ExportService().export_image(
                source,
                output,
                [],
                StyleSettings(),
                preserve_metadata=False,
            )

            with Image.open(output) as exported:
                self.assertNotIn(270, exported.getexif())


if __name__ == "__main__":
    unittest.main()
