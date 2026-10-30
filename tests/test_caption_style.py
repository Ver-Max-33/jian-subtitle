import hashlib
import json
import math
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from subtitle_app.caption_presets import apply_builtin, builtin_presets
from subtitle_app.font_catalog import bundled_font_dirs
from subtitle_app.models import CaptionRenderRequest, StyleSettings
from subtitle_app.render_service import RenderService
from subtitle_app.web_contracts import CommandError, style_patch
from subtitle_app.web_fonts import font_entries, font_id_for_style

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "src/subtitle_app/resources/fonts"
NOTO_SANS = ROOT / "frontend/public/fonts/NotoSansSC.ttf"
REFERENCE = ROOT / "tests/fixtures/caption-reference.png"
REFERENCE_TEXT = "同事：听说这次艾达王是大获全胜啊"


def ink(image, background):
    """Pixels that differ from a flat background colour."""
    pixels = np.asarray(image.convert("RGB")).astype(np.int16)
    return np.abs(pixels - np.array(background, np.int16)).max(axis=2) > 40


def entries_labelled(label):
    return [entry for entry in font_entries().values() if entry["label"] == label]


class BundledFontTests(unittest.TestCase):
    def test_bundled_fonts_match_their_lock_file(self):
        lock = json.loads((FONTS / "fonts.lock.json").read_text(encoding="utf-8"))
        for font in lock["fonts"]:
            with self.subTest(font=font["file"]):
                data = (FONTS / font["file"]).read_bytes()
                self.assertEqual(font["size"], len(data))
                self.assertEqual(font["sha256"], hashlib.sha256(data).hexdigest())
                self.assertTrue((FONTS / font["license"]).is_file())

    def test_bundled_font_directories_include_caption_and_interface_fonts(self):
        directories = {path.resolve() for path in bundled_font_dirs()}
        self.assertIn(FONTS.resolve(), directories)
        self.assertIn(NOTO_SANS.parent.resolve(), directories)

    def test_font_list_offers_every_bundled_font_with_its_chinese_name(self):
        for label in ("思源黑体", "思源宋体", "霞鹜文楷", "马善政楷书"):
            with self.subTest(label=label):
                entries = entries_labelled(label)
                self.assertTrue(entries)
                self.assertTrue(all(entry["bundled"] for entry in entries))

    def test_variable_fonts_list_each_named_weight(self):
        weights = sorted(entry["weight"] for entry in entries_labelled("思源黑体"))
        self.assertEqual([100, 200, 300, 400, 500, 600, 700, 800, 900], weights)
        black = next(entry for entry in entries_labelled("思源黑体") if entry["weight"] == 900)
        self.assertEqual("Black", black["variant"])
        self.assertEqual(list(range(200, 1000, 100)), sorted(entry["weight"] for entry in entries_labelled("思源宋体")))

    def test_static_fonts_have_no_weight_axis(self):
        self.assertEqual([None], [entry["weight"] for entry in entries_labelled("马善政楷书")])

    def test_choosing_a_weight_stores_it_with_the_font_file(self):
        black = next(entry for entry in entries_labelled("思源黑体") if entry["weight"] == 900)
        patch = style_patch({"font_id": black["id"]})
        self.assertEqual(900, patch["font_weight"])
        self.assertEqual(Path(black["path"]).resolve(), Path(patch["font_path"]).resolve())
        self.assertEqual(black["id"], font_id_for_style({**patch}))

    def test_a_style_without_weight_maps_to_the_regular_instance(self):
        regular = next(entry for entry in entries_labelled("思源黑体") if entry["weight"] == 400)
        style = {"font_path": regular["path"], "font_index": 0, "font_weight": None}
        self.assertEqual(regular["id"], font_id_for_style(style))


class FontWeightRenderingTests(unittest.TestCase):
    def render(self, **style):
        source = Image.new("RGB", (520, 200), "white")
        caption = [CaptionRenderRequest("思源黑体字重", (0.5, 0.5))]
        base = dict(font_size=56, font_path=str(NOTO_SANS), text_color=(0, 0, 0, 255), stroke_width=0)
        return RenderService().render(source, caption, StyleSettings(**{**base, **style}))

    def test_a_variable_font_without_weight_renders_regular_instead_of_thin(self):
        unset = ink(self.render(), (255, 255, 255)).sum()
        regular = ink(self.render(font_weight=400), (255, 255, 255)).sum()
        thin = ink(self.render(font_weight=100), (255, 255, 255)).sum()
        self.assertEqual(regular, unset)
        self.assertGreater(unset, thin * 1.3)

    def test_heavier_weights_put_more_ink_on_the_image(self):
        regular = ink(self.render(font_weight=400), (255, 255, 255)).sum()
        black = ink(self.render(font_weight=900), (255, 255, 255)).sum()
        self.assertGreater(black, regular * 1.3)


class SlantAndOutlineTests(unittest.TestCase):
    def test_slant_leans_the_tops_of_glyphs_to_the_right(self):
        source = Image.new("RGB", (400, 300), "white")
        style = StyleSettings(font_size=150, font_path=str(NOTO_SANS), font_weight=700, text_color=(0, 0, 0, 255), stroke_width=0, skew=20)
        mask = ink(RenderService().render(source, [CaptionRenderRequest("I", (0.5, 0.5))], style), (255, 255, 255))
        rows = np.nonzero(mask.any(axis=1))[0]
        top, bottom = rows[: len(rows) // 4], rows[-(len(rows) // 4):]
        shift = np.nonzero(mask[top])[1].mean() - np.nonzero(mask[bottom])[1].mean()
        expected = math.tan(math.radians(20)) * (bottom.mean() - top.mean())
        self.assertAlmostEqual(expected, shift, delta=expected * 0.15)

    def outline_width(self, skew):
        source = Image.new("RGB", (900, 260), (128, 128, 128))
        style = StyleSettings(font_size=80, font_path=str(NOTO_SANS), font_weight=900, stroke_width=12, skew=skew)
        rgb = np.asarray(RenderService().render(source, [CaptionRenderRequest("大获全胜", (0.5, 0.5))], style).convert("RGB")).astype(np.int16)
        fill = (rgb.min(axis=2) > 200).astype(np.uint8)
        outline = (rgb.max(axis=2) < 60).astype(np.uint8)
        distance = cv2.distanceTransform(1 - fill, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
        edge = outline - cv2.erode(outline, np.ones((3, 3), np.uint8))
        return float(np.median(distance[(edge > 0) & (distance > 2)]))

    def test_outline_keeps_the_requested_width_on_upright_text(self):
        self.assertAlmostEqual(12, self.outline_width(0), delta=1)

    def test_outline_keeps_the_requested_width_on_slanted_text(self):
        self.assertAlmostEqual(12, self.outline_width(19), delta=1)

    def test_measurement_matches_rendering_for_slanted_tight_text(self):
        renderer = RenderService()
        for angle in (0, 33):
            with self.subTest(angle=angle):
                style = StyleSettings(font_size=40, font_path=str(NOTO_SANS), font_weight=900, stroke_width=8, skew=19, letter_spacing=-4, max_width=.5, effect="glow")
                captions = [CaptionRenderRequest("第一行字幕\n第二行稍长一些的字幕", (.5, .7), angle)]
                measured = renderer.measure((800, 450), captions, style)
                rendered = []
                renderer.render(Image.new("RGB", (800, 450)), captions, style, geometry=rendered)
                self.assertEqual(measured, rendered)

    def test_negative_letter_spacing_draws_a_narrower_line(self):
        def width(spacing):
            source = Image.new("RGB", (900, 200), "white")
            style = StyleSettings(font_size=60, font_path=str(NOTO_SANS), text_color=(0, 0, 0, 255), stroke_width=0, letter_spacing=spacing)
            columns = np.nonzero(ink(RenderService().render(source, [CaptionRenderRequest("紧凑的字间距", (0.5, 0.5))], style), (255, 255, 255)).any(axis=0))[0]
            return columns.max() - columns.min()
        self.assertLess(width(-8), width(0) - 30)


class StyleContractTests(unittest.TestCase):
    def test_contract_accepts_slant_negative_spacing_and_thick_outlines(self):
        patch = style_patch({"skew": 19, "letter_spacing": -12, "stroke_width": 40})
        self.assertEqual({"skew": 19.0, "letter_spacing": -12, "stroke_width": 40}, patch)

    def test_contract_rejects_out_of_range_slant_and_spacing(self):
        for values in ({"skew": 45}, {"skew": -1}, {"letter_spacing": -500}, {"stroke_width": 500}):
            with self.subTest(values=values), self.assertRaises(CommandError):
                style_patch(values)


class BuiltinPresetTests(unittest.TestCase):
    def test_bold_outline_preset_scales_with_the_caption_size(self):
        for size, stroke in ((46, 9), (100, 20)):
            with self.subTest(size=size):
                overrides = apply_builtin("粗描边斜体", {**StyleSettings(font_size=size).to_mapping()})
                self.assertNotIn("font_size", overrides)
                self.assertEqual(stroke, overrides["stroke_width"])
                self.assertEqual(19, overrides["skew"])
                self.assertEqual(900, overrides["font_weight"])
                self.assertEqual(NOTO_SANS.resolve(), Path(overrides["font_path"]).resolve())

    def test_every_builtin_font_preset_points_at_a_listed_font(self):
        listed = {(Path(e["path"]).resolve(), e["index"], e["weight"]) for e in font_entries().values()}
        for name in builtin_presets():
            with self.subTest(name=name):
                overrides = apply_builtin(name, StyleSettings().to_mapping())
                if "font_path" in overrides:
                    self.assertIn((Path(overrides["font_path"]).resolve(), overrides["font_index"], overrides["font_weight"]), listed)

    def test_classic_looks_keep_the_caption_font(self):
        overrides = apply_builtin("经典", {**StyleSettings(font_size=80, font_path="x.ttf").to_mapping()})
        self.assertNotIn("font_path", overrides)
        self.assertNotIn("font_size", overrides)


class ReferenceCaptionTests(unittest.TestCase):
    """The bold outline preset must reproduce tests/fixtures/caption-reference.png (a real caption screenshot)."""

    @staticmethod
    def masks(rgb):
        white = (rgb.min(axis=2) > 200).astype(np.uint8)
        black = (rgb.max(axis=2) < 70).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
        ring = cv2.dilate(black, np.ones((3, 3), np.uint8))
        fill = np.zeros_like(white)
        for i in range(1, count):
            component = (labels == i).astype(np.uint8)
            edge = cv2.dilate(component, np.ones((3, 3), np.uint8)) - component
            if stats[i, cv2.CC_STAT_AREA] > 4 and (edge & ring).sum() / max(1, edge.sum()) > 0.8:
                fill |= component
        outline = black & cv2.dilate(fill, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
        return fill.astype(bool), (outline | fill).astype(bool)

    def test_bold_outline_preset_matches_the_reference_caption(self):
        reference = np.asarray(Image.open(REFERENCE).convert("RGB")).astype(np.int16)
        ref_fill, ref_shape = self.masks(reference)
        ys, xs = np.nonzero(ref_shape)
        ref_fill, ref_shape = ref_fill[ys.min():ys.max() + 1, xs.min():xs.max() + 1], ref_shape[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

        base = StyleSettings().to_mapping()
        style = StyleSettings.from_mapping({**base, **apply_builtin("粗描边斜体", {**base, "font_size": 46.5}), "font_size": 46.5, "max_width": 1.0})
        canvas = Image.new("RGB", (1000, 160), (128, 128, 128))
        rendered = np.asarray(RenderService().render(canvas, [CaptionRenderRequest(REFERENCE_TEXT, (0.5, 0.5))], style).convert("RGB")).astype(np.int16)
        fill, shape = self.masks(rendered)

        res = cv2.matchTemplate(fill.astype(np.float32), ref_fill.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        _, _, _, (bx, by) = cv2.minMaxLoc(res)
        best = (0.0, 0.0)
        h, w = ref_fill.shape
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = bx + dx, by + dy
                if x < 0 or y < 0 or y + h > fill.shape[0] or x + w > fill.shape[1]:
                    continue
                f, s = fill[y:y + h, x:x + w], shape[y:y + h, x:x + w]
                score = ((f & ref_fill).sum() / (f | ref_fill).sum(), (s & ref_shape).sum() / (s | ref_shape).sum())
                best = max(best, score, key=sum)
        # Calibrated on this screenshot: the matching style scores ~0.71 / 0.85 (a 4x supersampled render ~0.72 / 0.85);
        # a 4° slant error, Regular weight, a ±2 px outline or −3 px spacing each fall below these bars.
        self.assertGreaterEqual(best[0], 0.70, "white text should overlap the reference")
        self.assertGreaterEqual(best[1], 0.84, "outline should overlap the reference")


if __name__ == "__main__":
    unittest.main()
