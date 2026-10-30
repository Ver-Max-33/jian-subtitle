from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from .models import CaptionRenderRequest, StyleSettings
from .render_service import RenderService


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
        quality: int = 95,
        jpeg_background: tuple[int, int, int] = (255, 255, 255),
        on_ready=None,
    ) -> Path:
        source = Path(source_path).resolve()
        output = Path(output_path).resolve()
        if source == output:
            raise ValueError("输出路径不能覆盖源图")
        if output.exists():
            raise FileExistsError(f"输出文件已存在：{output.name}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}.{uuid4().hex}.tmp{output.suffix}")
        try:
            with Image.open(source) as opened:
                original_format = opened.format
                normalized = ImageOps.exif_transpose(opened)
                metadata = {
                    key: normalized.info[key]
                    for key in ("exif", "icc_profile")
                    if preserve_metadata and normalized.info.get(key)
                }
                base = normalized.convert("RGBA")
            rendered = self._renderer.render(base, captions, style)
            image_format, save_options = self._save_options(
                output, original_format, metadata
            )
            if image_format in {"JPEG", "BMP"}:
                background = Image.new("RGB", rendered.size, jpeg_background)
                background.paste(rendered, mask=rendered.getchannel("A"))
                rendered = background
            if image_format == "JPEG":
                save_options["quality"] = quality
            elif image_format == "WEBP":
                save_options.update(quality=quality, lossless=quality == 100)
            rendered.save(temporary, format=image_format, **save_options)
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
        temporary = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            if on_ready:
                on_ready(temporary)
            self._commit_no_clobber(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        return output

    @staticmethod
    def _commit_no_clobber(temporary: Path, output: Path) -> None:
        # Same-volume hard-link publication is atomic and fails if the name exists.
        # Never fall back to replace: unsupported filesystems must fail safely.
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if os.name == "nt":
            # Windows rename fails if the target exists, including FAT/exFAT volumes.
            os.rename(temporary, output)
        else:
            os.link(temporary, output)

    def _save_options(
        self,
        output: Path,
        original_format: str | None,
        metadata: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        extension_formats = {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".webp": "WEBP",
            ".bmp": "BMP",
        }
        image_format = extension_formats.get(output.suffix.lower())
        if image_format is None:
            image_format = "JPEG" if original_format == "JPG" else original_format
        if image_format not in {"JPEG", "PNG", "WEBP", "BMP"}:
            raise ValueError(f"不支持的输出格式：{output.suffix}")
        options: dict[str, object] = {}
        if image_format == "JPEG":
            options.update(quality=95, subsampling=0)
        elif image_format == "PNG":
            options["compress_level"] = 6
        elif image_format == "WEBP":
            options.update(lossless=True, quality=100, method=6)
        for key, value in metadata.items():
            if key == "exif" and image_format not in {"JPEG", "PNG", "WEBP"}:
                continue
            if key == "icc_profile" and image_format == "BMP":
                continue
            options[key] = value
        return image_format, options
