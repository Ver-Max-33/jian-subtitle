import errno
import io
import os
import stat
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageChops, ImageCms, PngImagePlugin

from subtitle_app.export_service import ExportService
from subtitle_app.models import CaptionRenderRequest, StyleSettings

CMYK_PROFILE = Path("/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc")


def exif_with_thumbnail(thumbnail: bytes) -> bytes:
    """EXIF as cameras write it: IFD0 (Make) linked to IFD1, a small JPEG preview of the picture."""
    make = b"AuditCam\x00"
    ifd1_offset = 8 + 2 + 12 + 4 + len(make)
    out = b"MM\x00\x2a" + struct.pack(">I", 8)
    out += struct.pack(">H", 1) + struct.pack(">HHII", 0x010F, 2, len(make), 8 + 2 + 12 + 4) + struct.pack(">I", ifd1_offset) + make
    thumbnail_offset = ifd1_offset + 2 + 3 * 12 + 4
    out += struct.pack(">H", 3) + struct.pack(">HHIHH", 0x0103, 3, 1, 6, 0) + struct.pack(">HHII", 0x0201, 4, 1, thumbnail_offset)
    out += struct.pack(">HHII", 0x0202, 4, 1, len(thumbnail)) + struct.pack(">I", 0)
    return b"Exif\x00\x00" + out + thumbnail


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

    # 2026-11-13 export audit.
    @unittest.skipIf(os.name == "nt", "Windows publishes with rename")
    def test_a_volume_without_hard_links_still_gets_the_files(self):
        # exFAT and FAT32 (USB sticks, SD cards) have no hard links: every image used to fail.
        def no_links(*_):
            raise OSError(errno.ENOTSUP, "Operation not supported")
        with tempfile.TemporaryDirectory() as directory, mock.patch("subtitle_app.export_service.os.link", no_links):
            root = Path(directory)
            Image.new("RGB", (40, 30), "white").save(root / "source.png")
            ExportService().export_image(root / "source.png", root / "out" / "result.png", [], StyleSettings())
            ExportService().copy_original(root / "source.png", root / "out" / "copy.png")
            self.assertEqual(["copy.png", "result.png"], sorted(p.name for p in (root / "out").iterdir()))

    @unittest.skipIf(os.name == "nt", "Windows publishes with rename")
    def test_without_hard_links_a_file_that_appears_meanwhile_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (40, 30), "white").save(root / "source.png")
            def someone_else(_, target):
                Path(target).write_bytes(b"theirs")
                raise OSError(errno.ENOTSUP, "Operation not supported")
            with mock.patch("subtitle_app.export_service.os.link", someone_else), self.assertRaises(FileExistsError):
                ExportService().export_image(root / "source.png", root / "result.png", [], StyleSettings())
            self.assertEqual(b"theirs", (root / "result.png").read_bytes())
            self.assertEqual(["result.png", "source.png"], sorted(p.name for p in root.iterdir()))

    def test_a_read_only_or_locked_source_is_copied_as_a_normal_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            Image.new("RGB", (40, 30), "white").save(source)
            os.utime(source, (1_600_000_000, 1_600_000_000))
            locked = hasattr(os, "chflags") and hasattr(stat, "UF_IMMUTABLE")
            source.chmod(0o444)
            if locked:
                os.chflags(source, stat.UF_IMMUTABLE)
            try:
                copied = ExportService().copy_original(source, root / "out" / "copy.png")
            finally:
                if locked:
                    os.chflags(source, 0)
                source.chmod(0o644)
            self.assertTrue(os.access(copied, os.W_OK))
            self.assertEqual(1_600_000_000, int(copied.stat().st_mtime))
            if locked:
                self.assertFalse(copied.stat().st_flags & stat.UF_IMMUTABLE)
            self.assertEqual(["copy.png"], [p.name for p in (root / "out").iterdir()])

    @unittest.skipIf(os.name == "nt", "long names need long-path support on Windows")
    def test_a_long_name_still_fits_its_temporary_file(self):
        # A name may have 255 bytes; a temporary named after a 236-byte output did not fit.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (40, 30), "white").save(root / "source.png")
            ExportService().export_image(root / "source.png", root / ("n" * 236 + ".png"), [], StyleSettings())
            ExportService().copy_original(root / "source.png", root / ("m" * 236 + ".png"))
            self.assertEqual(3, len(list(root.iterdir())))

    def test_a_leftover_from_a_crash_goes_when_the_file_is_written_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (40, 30), "white").save(root / "source.png")
            output = root / "out" / "result.png"
            output.parent.mkdir()
            ExportService.temporary_for(output).write_bytes(b"")
            ExportService().export_image(root / "source.png", output, [], StyleSettings())
            self.assertEqual(["result.png"], [p.name for p in output.parent.iterdir()])

    def test_16_bit_grey_keeps_its_tones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ramp = Image.linear_gradient("L").resize((256, 64)).convert("I").point(lambda v: v * 257).convert("I;16")
            ramp.save(root / "grey16.png")
            ExportService().export_image(root / "grey16.png", root / "out.png", [], StyleSettings())
            with Image.open(root / "out.png") as exported:
                grey = exported.convert("L")
                self.assertAlmostEqual(127.5, sum(grey.getdata()) / (grey.width * grey.height), delta=3)

    def test_lossless_webp_stays_lossless_when_the_format_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            noise = Image.effect_noise((64, 48), 80).convert("RGB")
            noise.save(root / "lossless.webp", lossless=True)
            ExportService().export_image(root / "lossless.webp", root / "out.webp", [], StyleSettings(), quality=None)
            with Image.open(root / "out.webp") as exported:
                self.assertIsNone(ImageChops.difference(exported.convert("RGB"), noise).getbbox())

    def test_jpeg_gets_exif_it_can_read_from_a_webp(self):
        # WebP keeps EXIF without its "Exif" header; copied as is, JPEG readers found nothing.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exif = Image.Exif()
            exif[0x010F] = "Cam"
            Image.new("RGB", (40, 30), "white").save(root / "source.webp", exif=exif.tobytes()[6:])
            ExportService().export_image(root / "source.webp", root / "out.jpg", [], StyleSettings())
            with Image.open(root / "out.jpg") as exported:
                self.assertEqual("Cam", exported.getexif().get(0x010F))

    def test_the_cameras_preview_without_the_caption_is_left_out(self):
        # File browsers show that tiny preview: the picture as it was, without its caption.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preview = io.BytesIO()
            Image.new("RGB", (160, 120), "red").save(preview, "JPEG")
            Image.new("RGB", (400, 300), "blue").save(root / "source.jpg", exif=exif_with_thumbnail(preview.getvalue()))
            ExportService().export_image(root / "source.jpg", root / "out.jpg", [CaptionRenderRequest("Caption")], StyleSettings(font_size=16))
            with Image.open(root / "out.jpg") as exported:
                self.assertEqual("AuditCam", exported.getexif().get(0x010F))
                self.assertNotIn(b"\xff\xd8\xff", exported.info["exif"][6:])

    def test_colour_profile_and_print_size_stay_without_metadata(self):
        # They decide how the picture looks and prints and say nothing about the person; EXIF goes.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
            exif = Image.Exif()
            exif[0x010F] = "Cam"
            Image.new("RGB", (40, 30), (240, 0, 0)).save(root / "source.jpg", icc_profile=profile, dpi=(300, 300), exif=exif)
            for name in ("out.jpg", "out.png", "out.webp"):
                ExportService().export_image(root / "source.jpg", root / name, [], StyleSettings(), preserve_metadata=False)
                with Image.open(root / name) as exported:
                    self.assertEqual(profile, exported.info.get("icc_profile"), name)
                    self.assertNotIn(0x010F, exported.getexif(), name)
                    if name != "out.webp":
                        self.assertEqual((300, 300), tuple(round(v) for v in exported.info["dpi"]), name)

    def test_notes_and_xmp_stay_only_with_metadata(self):
        # 保留图片元数据 keeps them all; PNG text often holds the settings an AI picture was made with.
        xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:description>kept</dc:description></rdf:Description></rdf:RDF></x:xmpmeta>'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (40, 30), "white").save(root / "source.jpg", xmp=xmp, comment=b"a note")
            text = PngImagePlugin.PngInfo()
            text.add_text("parameters", "steps: 20")
            Image.new("RGB", (40, 30), "white").save(root / "source.png", pnginfo=text)
            ExportService().export_image(root / "source.jpg", root / "out.jpg", [], StyleSettings())
            ExportService().export_image(root / "source.png", root / "out.png", [], StyleSettings())
            ExportService().export_image(root / "source.jpg", root / "xmp.png", [], StyleSettings())
            ExportService().export_image(root / "source.jpg", root / "off.jpg", [], StyleSettings(), preserve_metadata=False)
            ExportService().export_image(root / "source.png", root / "off.png", [], StyleSettings(), preserve_metadata=False)
            with Image.open(root / "out.jpg") as jpg, Image.open(root / "out.png") as png, Image.open(root / "xmp.png") as converted:
                self.assertIn(b"kept", jpg.info.get("xmp", b""))
                self.assertEqual(b"a note", jpg.info.get("comment"))
                self.assertEqual("steps: 20", png.text.get("parameters"))
                self.assertIn("kept", converted.text.get("XML:com.adobe.xmp", ""))
            with Image.open(root / "off.jpg") as jpg, Image.open(root / "off.png") as png:
                self.assertFalse({"xmp", "comment"} & set(jpg.info))
                self.assertEqual({}, dict(png.text))

    def test_exif_too_long_for_jpeg_does_not_stop_the_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            big = Image.Exif()
            big[0x010F] = "Cam"
            big.get_ifd(0x8769)[0x9286] = b"ASCII\x00\x00\x00" + b"x" * 70000
            Image.new("RGB", (40, 30), "white").save(root / "source.png", exif=big.tobytes())
            ExportService().export_image(root / "source.png", root / "out.jpg", [], StyleSettings())
            with Image.open(root / "out.jpg") as exported:
                self.assertEqual("Cam", exported.getexif().get(0x010F))

    @unittest.skipUnless(CMYK_PROFILE.is_file(), "needs a CMYK profile")
    def test_cmyk_is_converted_through_its_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cmyk = CMYK_PROFILE.read_bytes()
            Image.new("CMYK", (40, 30), (0, 255, 255, 0)).save(root / "source.jpg", icc_profile=cmyk)
            ExportService().export_image(root / "source.jpg", root / "out.jpg", [], StyleSettings())
            with Image.open(root / "out.jpg") as exported:
                profile = exported.info.get("icc_profile")
                self.assertTrue(profile is None or profile[16:20] == b"RGB ")
                managed = ImageCms.profileToProfile(Image.open(root / "source.jpg"), io.BytesIO(cmyk), ImageCms.createProfile("sRGB"), outputMode="RGB")
                difference = ImageChops.difference(exported.convert("RGB"), managed).getextrema()
                self.assertLessEqual(max(high for _, high in difference), 12)


if __name__ == "__main__":
    unittest.main()
