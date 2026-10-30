from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
import math
from collections import OrderedDict

import cv2
import numpy as np
from fontTools.ttLib import TTFont, TTLibError
from PIL import Image, ImageChops, ImageDraw, ImageFont

from .font_catalog import FontCatalog
from .models import CaptionRenderRequest, StyleSettings

REGULAR_WEIGHT = 400
# Layers up to this many pixels are drawn at 2x so outlines grown from the glyphs stay smooth.
SUPERSAMPLED_AREA = 1_500_000


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    x: float  # left of the line's advance box, layer pixels, before slant
    top: float  # Pillow's "la" anchor: top of the ascender


@dataclass(frozen=True, slots=True)
class _Layout:
    style: StyleSettings
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    lines: tuple[_Line, ...]
    ascent: float
    spacing: float
    ink: tuple[float, float, float, float]  # outline-inclusive text box inside the layer
    background_padding: int
    size: tuple[int, int]
    # Picture pixels per reference pixel: the fixed minimums (padding, offsets) scale with the sizes. 1 for pixel styles.
    unit: float = 1.0


def scaled_style(style: StyleSettings, image_size: tuple[int, int]) -> StyleSettings:
    """Pixel sizes for this picture: a style with a reference edge keeps its share of the short edge (spec 4.2)."""
    edge = min(image_size)
    if style.reference_edge is None or edge <= 0:
        return style
    factor = edge / style.reference_edge
    return replace(style, font_size=style.font_size * factor, stroke_width=style.stroke_width * factor,
                   line_spacing=style.line_spacing * factor, letter_spacing=style.letter_spacing * factor)


class RenderService:
    """Renders both previews and final exports through the same interface."""

    def __init__(self):
        self._fonts = OrderedDict()

    def _font(self, style: StyleSettings, size: float):
        stamp = None
        if style.font_path:
            stat = Path(style.font_path).stat()
            stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        key = (style.font_path, style.font_family, size, style.font_index, style.font_weight, stamp)
        if key not in self._fonts:
            font = self._load_font(style, size)
            self._apply_weight(font, style.font_weight)
            self._fonts[key] = font
        self._fonts.move_to_end(key)
        while len(self._fonts) > 16:
            self._fonts.popitem(last=False)
        return self._fonts[key]

    def _text_layout(self, image_size, caption, style) -> _Layout:
        source = caption.style or style
        current = scaled_style(source, image_size)
        unit = min(image_size) / source.reference_edge if source.reference_edge and min(image_size) > 0 else 1.0
        font = self._font(current, current.font_size)
        draw = ImageDraw.Draw(Image.new("L", (1, 1)))
        stroke = current.stroke_width
        # Letters may overlap by half a glyph at most; beyond that the order of the text would flip.
        spacing = max(current.letter_spacing, -0.5 * current.font_size)
        slope = math.tan(math.radians(current.skew))
        ascent, descent = font.getmetrics() if isinstance(font, ImageFont.FreeTypeFont) else (current.font_size, 0)
        wrapped = self._wrap_text(draw, caption.text, font, max(24, round(image_size[0] * current.max_width)), stroke, spacing, slope * (ascent + descent))
        texts = wrapped.split("\n")
        pitch = draw.textbbox((0, 0), "A", font=font)[3] + 2 * stroke + current.line_spacing
        widths = [self._advance(draw, text, font, spacing) for text in texts]
        block = max(widths, default=0)
        origins = []
        box = None
        for number, (text, width) in enumerate(zip(texts, widths)):
            x = 0 if current.alignment == "left" else block - width if current.alignment == "right" else (block - width) / 2
            y = number * pitch
            origins.append((text, x, y))
            ink = self._line_ink(draw, text, font, spacing)
            if ink is None:
                continue
            left, top, right, bottom = ink
            # Slanting about the baseline moves the ascender right and the descender left.
            line_box = (x + left + slope * (ascent - bottom) - stroke, y + top - stroke, x + right + slope * (ascent - top) + stroke, y + bottom + stroke)
            box = line_box if box is None else (min(box[0], line_box[0]), min(box[1], line_box[1]), max(box[2], line_box[2]), max(box[3], line_box[3]))
        if box is None:
            box = (0.0, 0.0, 1.0, float(ascent + descent))
        text_width, text_height = max(1, box[2] - box[0]), max(1, box[3] - box[1])
        background_padding = max(8 * unit, current.font_size * .18) if current.show_background else 0
        effect_padding = max(4 * unit, current.font_size * .2) if current.effect != "none" else 2 * unit
        if source.reference_edge is None:
            # Pixel styles keep whole-pixel padding exactly as before; proportional ones keep fractions to stay in proportion.
            background_padding, effect_padding = round(background_padding), round(effect_padding)
        padding = max(background_padding, effect_padding) + 2 * unit
        size = (int(text_width + 2 * padding + .999), int(text_height + 2 * padding + .999))
        if size[0] * size[1] > 32_000_000:
            raise ValueError("字幕面积过大，请减小字号或拆分文字")
        dx, dy = padding - box[0], padding - box[1]
        lines = tuple(_Line(text, x + dx, y + dy) for text, x, y in origins)
        return _Layout(current, font, lines, ascent, spacing, (padding, padding, padding + text_width, padding + text_height), background_padding, size, unit)

    @staticmethod
    def rotated_size(size, angle):
        """Match Pillow's centered rotate(expand=True) without allocating a bitmap."""
        angle %= 360
        w, h = size
        if angle in (0, 180):
            return size
        if angle in (90, 270):
            return h, w
        radians = -math.radians(angle)
        a, b = round(math.cos(radians), 15), round(math.sin(radians), 15)
        d, e = -b, a
        c, f = a * (-w / 2) + b * (-h / 2) + w / 2, d * (-w / 2) + e * (-h / 2) + h / 2
        points = [(a*x + b*y + c, d*x + e*y + f) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]
        return (math.ceil(max(p[0] for p in points)) - math.floor(min(p[0] for p in points)),
                math.ceil(max(p[1] for p in points)) - math.floor(min(p[1] for p in points)))

    @classmethod
    def _geometry(cls, image_size, caption, current, unrotated, rotated):
        width, height = image_size
        rw, rh = rotated
        margin = min(12, width // 20, height // 20) if current.safe_edge else 0
        left = round(caption.position_ratio[0] * width - rw / 2)
        top = round(caption.position_ratio[1] * height - rh / 2)
        if current.safe_edge:
            left = round(cls._clamp(left, margin, max(margin, width - rw - margin)))
            top = round(cls._clamp(top, margin, max(margin, height - rh - margin)))
        return {"x": (left + rw / 2) / width, "y": (top + rh / 2) / height,
                "width": current.max_width, "height": unrotated[1] / height,
                "renderWidth": unrotated[0] / width, "rotation": caption.rotation,
                "bounds": (left, top, left + rw, top + rh),
                "overflow": left < 0 or top < 0 or left + rw > width or top + rh > height}

    def measure(self, image_size, captions, style):
        geometry = []
        for caption in captions:
            layout = self._text_layout(image_size, caption, style)
            geometry.append(self._geometry(image_size, caption, layout.style, layout.size, self.rotated_size(layout.size, caption.rotation)))
        return geometry

    def render(self, source: Image.Image, captions: list[CaptionRenderRequest], style: StyleSettings, *, geometry=None, layers=None, layers_only: bool = False) -> Image.Image:
        # Editing needs the exact text layers, not a newly composited 4K background.
        # The final export path retains its existing rasterization and compositing.
        result = source if layers_only else source.convert("RGBA").copy()
        for caption in captions:
            layout = self._text_layout(result.size, caption, style)
            layer = self._draw_layer(layout)
            unrotated = layer.size
            if layers is not None:
                layers.append(layer.copy())
            if caption.rotation:
                layer = layer.rotate(caption.rotation, resample=Image.Resampling.BICUBIC, expand=True)
            item_geometry = self._geometry(result.size, caption, layout.style, unrotated, layer.size)
            left, top = item_geometry["bounds"][:2]
            if geometry is not None:
                geometry.append(item_geometry)
            if not layers_only:
                result.alpha_composite(layer, (left, top))
        return result

    def _draw_layer(self, layout: _Layout) -> Image.Image:
        """Masks first, then paint: background, effect, outline, fill. Premultiplied float RGBA."""
        style = layout.style
        width, height = layout.size
        scale = 2 if width * height <= SUPERSAMPLED_AREA else 1
        text = self._text_mask(layout, scale)
        canvas = np.zeros((height * scale, width * scale, 4), np.float32)
        if style.show_background:
            left, top, right, bottom = layout.ink
            pad = layout.background_padding
            panel = Image.new("L", (width * scale, height * scale), 0)
            ImageDraw.Draw(panel).rounded_rectangle(tuple(v * scale for v in (left - pad, top - pad, right + pad, bottom + pad)), radius=round(max(6 * layout.unit, pad // 2) * scale), fill=255)
            self._paint(canvas, style.background_color, np.asarray(panel, np.float32) / 255)
        self._paint_effect(canvas, text, style, scale, layout.unit)
        if style.stroke_width > 0:
            self._paint(canvas, style.stroke_color, self._grow(text, style.stroke_width * scale))
        self._paint(canvas, style.text_color, text)
        if scale > 1:
            canvas = canvas.reshape(height, scale, width, scale, 4).mean(axis=(1, 3))
        alpha = canvas[..., 3:4]
        rgb = np.divide(canvas[..., :3], alpha, out=np.zeros_like(canvas[..., :3]), where=alpha > 1e-6)
        pixels = (np.concatenate([rgb, alpha], axis=2) * 255).round().clip(0, 255).astype(np.uint8)
        return Image.fromarray(pixels, "RGBA")

    def _text_mask(self, layout: _Layout, scale: int) -> np.ndarray:
        style = layout.style
        font = layout.font if scale == 1 else self._font(style, style.font_size * scale)
        size = (layout.size[0] * scale, layout.size[1] * scale)
        mask = Image.new("L", size, 0)
        slope = math.tan(math.radians(style.skew))
        ascent = layout.ascent * scale
        for line in layout.lines:
            if not line.text:
                continue
            strip = Image.new("L", size, 0) if slope else mask
            self._draw_line(ImageDraw.Draw(strip), (line.x * scale, line.top * scale), line.text, font, layout.spacing * scale)
            if slope:
                baseline = line.top * scale + ascent
                strip = strip.transform(size, Image.Transform.AFFINE, (1, slope, -slope * baseline, 0, 1, 0), resample=Image.Resampling.BICUBIC)
                mask = ImageChops.lighter(mask, strip)
        return np.asarray(mask, np.float32) / 255

    def _paint_effect(self, canvas, text, style: StyleSettings, scale: int, unit: float = 1.0) -> None:
        if style.effect == "none":
            return
        offset = max(2 * unit, round(style.font_size * 0.06))
        if style.effect == "shadow":
            self._paint(canvas, (0, 0, 0, 170), self._shift(text, round(offset * scale), round(offset * scale)))
        elif style.effect == "glow":
            spread = self._grow(text, max(2 * unit, style.stroke_width + offset // 2) * scale) * (230 / 255)
            sigma = max(2 * unit, offset) * scale
            self._paint(canvas, style.stroke_color[:3] + (255,), cv2.GaussianBlur(spread, (0, 0), sigma))
        elif style.effect == "outline":
            self._paint(canvas, style.stroke_color, self._grow(text, max(2 * unit, style.stroke_width + offset // 2) * scale))
        elif style.effect == "relief":
            half = round(offset / 2 * scale)
            self._paint(canvas, (255, 255, 255, 175), self._shift(text, -half, -half))
            self._paint(canvas, (0, 0, 0, 175), self._shift(text, half, half))

    @staticmethod
    def _paint(canvas: np.ndarray, color, mask: np.ndarray) -> None:
        """Premultiplied "over": paint a flat colour through a 0–1 coverage mask."""
        alpha = mask * (color[3] / 255)
        keep = 1 - alpha
        for channel in range(3):
            canvas[..., channel] = canvas[..., channel] * keep + alpha * (color[channel] / 255)
        canvas[..., 3] = canvas[..., 3] * keep + alpha

    @staticmethod
    def _grow(mask: np.ndarray, radius: float) -> np.ndarray:
        """Round-cornered outline: everything within `radius` of the glyphs, antialiased on its edge."""
        solid = (mask >= 0.5).astype(np.uint8)
        distance = cv2.distanceTransform(1 - solid, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        return np.maximum(np.clip(radius + 0.5 - distance, 0, 1), mask)

    @staticmethod
    def _shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
        moved = np.zeros_like(mask)
        h, w = mask.shape
        moved[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)] = mask[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)]
        return moved

    @classmethod
    def _advance(cls, draw, text, font, spacing) -> float:
        if not text:
            return 0.0
        if not spacing:
            return draw.textlength(text, font=font)
        return sum(draw.textlength(c, font=font) for c in text) + (len(text) - 1) * spacing

    @classmethod
    def _line_ink(cls, draw, text, font, spacing):
        """Ink box of a line drawn at (0, 0) with the "la" anchor; None for a blank line."""
        if not text.strip():
            return None
        if not spacing:
            return draw.textbbox((0, 0), text, font=font)
        boxes, x = [], 0.0
        for char in text:
            if not char.isspace():
                left, top, right, bottom = draw.textbbox((x, 0), char, font=font)
                boxes.append((left, top, right, bottom))
            x += draw.textlength(char, font=font) + spacing
        return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))

    @staticmethod
    def _draw_line(draw, position, text, font, spacing) -> None:
        if not spacing:
            draw.text(position, text, font=font, fill=255)
            return
        x, y = position
        for char in text:
            draw.text((x, y), char, font=font, fill=255)
            x += draw.textlength(char, font=font) + spacing

    @staticmethod
    def _wrap_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
        stroke_width: int,
        letter_spacing: float = 0,
        slant: float = 0,
    ) -> str:
        def width(value: str) -> float:
            return RenderService._text_width(draw, value, font, stroke_width, letter_spacing) + slant

        lines: list[str] = []
        for paragraph in text.split("\n"):
            remaining = paragraph
            if not remaining:
                lines.append("")
                continue
            while remaining:
                if width(remaining) <= max_width:
                    lines.append(remaining.rstrip())
                    break
                low, high = 1, len(remaining)
                while low < high:
                    middle = (low + high + 1) // 2
                    if width(remaining[:middle]) <= max_width:
                        low = middle
                    else:
                        high = middle - 1
                cutoff = max(1, low)
                whitespace = max(
                    remaining.rfind(" ", 0, cutoff + 1),
                    remaining.rfind("\t", 0, cutoff + 1),
                )
                if whitespace > 0:
                    cutoff = whitespace
                lines.append(remaining[:cutoff].rstrip())
                remaining = remaining[cutoff:].lstrip()
        return "\n".join(lines)

    @staticmethod
    def _load_font(
        style: StyleSettings, size: float,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates: list[str] = []
        if style.font_path:
            return ImageFont.truetype(style.font_path, size=size, index=style.font_index)
        if style.font_family:
            resolved = FontCatalog().find_path(style.font_family)
            if resolved is not None:
                candidates.append(str(resolved))
            family_files = {
                "Microsoft YaHei UI": "msyh.ttc",
                "Microsoft YaHei": "msyh.ttc",
                "微软雅黑": "msyh.ttc",
                "SimHei": "simhei.ttf",
                "黑体": "simhei.ttf",
                "KaiTi": "simkai.ttf",
                "楷体": "simkai.ttf",
                "FangSong": "simfang.ttf",
                "仿宋": "simfang.ttf",
                "Segoe UI": "segoeui.ttf",
                "PingFang SC": "PingFang.ttc",
            }
            candidates.extend(
                filter(
                    None,
                    (
                        style.font_family,
                        family_files.get(style.font_family),
                        f"{style.font_family}.ttf",
                    ),
                )
            )
        candidates.extend(
            (
                "C:/Windows/Fonts/msyh.ttc",
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Medium.ttc",
                "DejaVuSans.ttf",
            )
        )
        search_directories = (
            Path("C:/Windows/Fonts"),
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
        )
        for candidate in candidates:
            attempts = [candidate]
            if not Path(candidate).is_absolute():
                attempts.extend(str(directory / candidate) for directory in search_directories)
            for attempt in attempts:
                try:
                    return ImageFont.truetype(attempt, size=size)
                except OSError:
                    continue
        return ImageFont.load_default(size=size)

    @staticmethod
    def _apply_weight(font, weight: int | None) -> None:
        """Variable fonts start at their default instance (Thin for 思源黑体); pick the requested weight, else Regular."""
        path = getattr(font, "path", None)
        if not isinstance(font, ImageFont.FreeTypeFont) or not path:
            return
        axes = _variation_axes(str(path), getattr(font, "index", 0))
        if not axes:
            return
        target = REGULAR_WEIGHT if weight is None else weight
        font.set_variation_by_axes([min(high, max(low, target)) if tag == "wght" else default for tag, low, default, high in axes])

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _text_width(draw, text, font, stroke_width=0, letter_spacing=0) -> float:
        box = draw.textbbox((0, 0), text or " ", font=font, stroke_width=stroke_width)
        if not letter_spacing or len(text) < 2:
            return box[2] - box[0]
        last = draw.textbbox((0, 0), text[-1], font=font, stroke_width=stroke_width)
        first = draw.textbbox((0, 0), text[0], font=font, stroke_width=stroke_width)
        return sum(draw.textlength(c, font=font) for c in text[:-1]) + last[2] - first[0] + (len(text) - 1) * letter_spacing


@lru_cache(maxsize=64)
def _variation_axes(path: str, index: int) -> tuple[tuple[str, float, float, float], ...]:
    try:
        with TTFont(path, fontNumber=index, lazy=True) as font:
            if "fvar" not in font:
                return ()
            return tuple((axis.axisTag, axis.minValue, axis.defaultValue, axis.maxValue) for axis in font["fvar"].axes)
    except (OSError, TTLibError):
        return ()
