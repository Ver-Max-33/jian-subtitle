from __future__ import annotations

import errno
import hashlib
import io
import os
import shutil
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, PngImagePlugin

from .models import CaptionRenderRequest, StyleSettings
from .render_service import RenderService

SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
# A JPEG APP1 segment holds 64 KB, its own header included.
JPEG_EXIF_LIMIT = 65533
# What link() says on exFAT and FAT32 (USB sticks, SD cards) and some network shares: they have no hard links.
NO_LINKS = {errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM}


def picture(image: Image.Image) -> tuple[Image.Image, bytes | None]:
    """The picture in RGBA as it should look, and the colour profile those pixels are in (None: plain sRGB)."""
    icc = image.info.get("icc_profile") or None
    space = icc[16:20] if icc and len(icc) >= 20 else None
    if image.mode.startswith("I;16"):
        # 16-bit grey: a straight conversion to 8 bits clips everything above 255 to white.
        image = image.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    if image.mode == "CMYK" and space == b"CMYK":
        try:
            converted = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(io.BytesIO(icc)), ImageCms.ImageCmsProfile(io.BytesIO(SRGB)), outputMode="RGB")
            return converted.convert("RGBA"), SRGB
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass
    # A CMYK or grey profile does not describe RGB pixels; it would make them look wrong.
    return image.convert("RGBA"), icc if space == b"RGB " else None


def lossless_webp(path: Path) -> bool:
    """Whether a WebP file is losslessly compressed (its image is a VP8L chunk)."""
    with open(path, "rb") as stream:
        header = stream.read(12)
        if header[:4] != b"RIFF" or header[8:] != b"WEBP":
            return False
        while len(chunk := stream.read(8)) == 8:
            kind, size = chunk[:4], int.from_bytes(chunk[4:], "little")
            if kind in {b"VP8L", b"VP8 ", b"ANMF"}:
                return kind == b"VP8L"
            stream.seek(size + (size & 1), os.SEEK_CUR)
    return False


def exif_for(image: Image.Image, image_format: str) -> bytes | None:
    """The source's EXIF, written fresh: with the header every format expects and without the camera's own preview,
    which shows the picture as it was, without its caption."""
    if not image.info.get("exif"):
        return None
    exif = image.getexif()
    data = exif.tobytes()
    if image_format == "JPEG" and len(data) > JPEG_EXIF_LIMIT:
        # Keep what says when, where and with what; drop the free-form notes that do not fit a JPEG.
        details = exif.get_ifd(0x8769)
        for tag in (0x927C, 0x9286):  # MakerNote, UserComment
            details.pop(tag, None)
        data = exif.tobytes()
        if len(data) > JPEG_EXIF_LIMIT:
            return None
    return data


class ExportService:
    """Writes rendered images without ever overwriting their source."""

    def __init__(self, renderer: RenderService | None = None) -> None:
        self._renderer = renderer or RenderService()

    def export_image(
        self,
        source_path: Path,
        output_path: Path,
        captions: list[CaptionRenderRequest],
        style: StyleSettings,
        *,
        preserve_metadata: bool = True,
        quality: int | None = 95,
        jpeg_background: tuple[int, int, int] = (255, 255, 255),
        on_ready=None,
    ) -> Path:
        """`quality` None keeps the source's own character (保持原格式): a lossless WebP stays lossless."""
        source = Path(source_path).resolve()
        output = Path(output_path).resolve()
        if source == output:
            raise ValueError("输出路径不能覆盖源图")
        if output.exists():
            raise FileExistsError(f"输出文件已存在：{output.name}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.temporary_for(output)
        try:
            temporary.unlink(missing_ok=True)
            with Image.open(source) as opened:
                original_format = opened.format
                normalized = ImageOps.exif_transpose(opened)
                base, icc = picture(normalized)
                info = normalized.info
                image_format = self._format(output, original_format)
                exif = exif_for(normalized, image_format) if preserve_metadata else None
                xmp = info.get("xmp") if preserve_metadata else None
                # PNG text (AI pictures keep their settings there) and JPEG comments go with the rest of the metadata.
                texts = dict(getattr(opened, "text", None) or {}) if preserve_metadata and original_format == "PNG" else {}
                comment = info.get("comment") if preserve_metadata else None
            rendered = self._renderer.render(base, captions, style)
            if image_format in {"JPEG", "BMP"}:
                background = Image.new("RGB", rendered.size, jpeg_background)
                background.paste(rendered, mask=rendered.getchannel("A"))
                rendered = background
            # The colour profile and print size decide how the picture looks and prints, so they always stay;
            # EXIF and XMP (camera, time, place) only with 保留图片元数据.
            options: dict[str, object] = {}
            if icc and image_format != "BMP":
                options["icc_profile"] = icc
            if info.get("dpi") and image_format != "WEBP":
                options["dpi"] = info["dpi"]
            if exif and image_format != "BMP":
                options["exif"] = exif
            if xmp and image_format in {"JPEG", "WEBP"}:
                options["xmp"] = xmp
            if comment and image_format == "JPEG":
                options["comment"] = comment
            if image_format == "PNG" and (texts or xmp):
                chunks = PngImagePlugin.PngInfo()
                for key, value in texts.items():
                    chunks.add_text(key, value)
                if xmp and "XML:com.adobe.xmp" not in texts:
                    chunks.add_itxt("XML:com.adobe.xmp", xmp.decode("utf-8", "replace") if isinstance(xmp, bytes) else xmp)
                options["pnginfo"] = chunks
            if image_format == "JPEG":
                options.update(quality=quality or 95, subsampling=0)
            elif image_format == "PNG":
                options["compress_level"] = 6
            elif image_format == "WEBP":
                lossless = quality == 100 or (quality is None and original_format == "WEBP" and lossless_webp(source))
                options.update(quality=quality or 95, lossless=lossless, method=6)
            rendered.save(temporary, format=image_format, **options)
            if on_ready:
                on_ready(temporary)
            self._commit_no_clobber(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return output

    def copy_original(self, source_path: Path, output_path: Path, *, on_ready=None) -> Path:
        source = Path(source_path).resolve()
        output = Path(output_path).resolve()
        if source == output:
            raise ValueError("输出路径不能覆盖源图")
        if output.exists():
            raise FileExistsError(f"输出文件已存在：{output.name}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.temporary_for(output)
        try:
            temporary.unlink(missing_ok=True)
            # The bytes and the dates, not a read-only bit or a Finder lock: the copy would be unwritable here and
            # undeletable afterwards.
            shutil.copyfile(source, temporary)
            dates = source.stat()
            os.utime(temporary, ns=(dates.st_atime_ns, dates.st_mtime_ns))
            if on_ready:
                on_ready(temporary)
            self._commit_no_clobber(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return output

    @staticmethod
    def temporary_for(output: Path) -> Path:
        """Where a file is written before it takes its name. Short, so every name that fits fits this too; the same
        on every attempt, so writing the file again clears what a crash left behind."""
        return output.with_name(f".jian-{hashlib.sha256(output.name.encode()).hexdigest()[:16]}.tmp")

    @staticmethod
    def _commit_no_clobber(temporary: Path, output: Path) -> None:
        # Never replace a file that is already there.
        # Windows can only flush a handle opened for writing (FlushFileBuffers); read-only fails with EBADF.
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        if os.name == "nt":
            # Windows rename fails if the target exists, including FAT/exFAT volumes.
            os.rename(temporary, output)
            return
        try:
            # Same-volume hard-link publication is atomic and fails if the name exists.
            os.link(temporary, output)
        except OSError as error:
            if error.errno not in NO_LINKS:
                raise
            # No hard links here: claim the name (O_EXCL fails if anyone has it), then move the file over the claim.
            os.close(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
            try:
                os.replace(temporary, output)
            except OSError:
                output.unlink(missing_ok=True)
                raise

    @staticmethod
    def _format(output: Path, original_format: str | None) -> str:
        extension_formats = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".bmp": "BMP"}
        image_format = extension_formats.get(output.suffix.lower())
        if image_format is None:
            image_format = "JPEG" if original_format == "JPG" else original_format
        if image_format not in {"JPEG", "PNG", "WEBP", "BMP"}:
            raise ValueError(f"不支持的输出格式：{output.suffix}")
        return image_format
