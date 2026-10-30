import unittest
from pathlib import Path

from PIL import Image, ImageChops

from subtitle_app.models import CaptionRenderRequest, StyleSettings
from subtitle_app.render_service import RenderService, scaled_style

NOTO_SANS = Path(__file__).resolve().parents[1] / "frontend/public/fonts/NotoSansSC.ttf"


class RenderServiceTests(unittest.TestCase):
    def test_geometry_measurement_matches_rendered_layers_without_a_source_image(self):
        renderer = RenderService()
        for angle in (0, 90, -90, 180, 17, -43.5):
            for spacing in (0, 3):
                with self.subTest(angle=angle, spacing=spacing):
                    style = StyleSettings(font_size=32, max_width=.4, letter_spacing=spacing,
                                          show_background=True, effect="shadow")
                    captions = [CaptionRenderRequest("Speaker: first line\nAnother long line", (.9, .8), angle)]
                    measured = renderer.measure((640, 480), captions, style)
                    rendered = []
                    renderer.render(Image.new("RGB", (640, 480)), captions, style, geometry=rendered)
                    self.assertEqual(measured, rendered)

    def test_rendering_changes_the_result_without_mutating_the_source(self):
        source = Image.new("RGB", (640, 360), "white")
        original = source.copy()

        rendered = RenderService().render(
            source,
            [CaptionRenderRequest("Caption", position_ratio=(0.5, 0.82))],
            StyleSettings(font_size=36, text_color=(20, 20, 20, 255)),
        )

        self.assertIsNone(ImageChops.difference(source, original).getbbox())
        self.assertEqual(source.size, rendered.size)
        self.assertIsNotNone(ImageChops.difference(rendered.convert("RGB"), source).getbbox())

    def test_out_of_range_position_is_clamped_back_inside_the_image(self):
        source = Image.new("RGB", (320, 180), "white")

        rendered = RenderService().render(
            source,
            [CaptionRenderRequest("Visible", position_ratio=(1.5, 1.5))],
            StyleSettings(font_size=28, text_color=(0, 0, 0, 255)),
        )

        self.assertIsNotNone(ImageChops.difference(rendered.convert("RGB"), source).getbbox())

    def test_background_option_draws_a_padded_caption_panel(self):
        source = Image.new("RGB", (420, 220), "black")
        request = [CaptionRenderRequest("Panel", position_ratio=(0.5, 0.5))]
        plain = RenderService().render(
            source,
            request,
            StyleSettings(font_size=34, stroke_width=0),
        )
        with_background = RenderService().render(
            source,
            request,
            StyleSettings(
                font_size=34,
                stroke_width=0,
                show_background=True,
                background_color=(200, 40, 30, 220),
            ),
        )

        plain_difference = ImageChops.difference(plain.convert("RGB"), source)
        panel_difference = ImageChops.difference(with_background.convert("RGB"), source)
        plain_pixels = sum(
            1
            for pixel in plain_difference.get_flattened_data()
            if pixel != (0, 0, 0)
        )
        panel_pixels = sum(
            1
            for pixel in panel_difference.get_flattened_data()
            if pixel != (0, 0, 0)
        )
        self.assertGreater(panel_pixels, plain_pixels)

    def test_every_advertised_text_effect_changes_the_rendered_result(self):
        source = Image.new("RGB", (420, 220), "white")
        request = [CaptionRenderRequest("Effect", position_ratio=(0.5, 0.5))]
        plain = RenderService().render(
            source,
            request,
            StyleSettings(
                font_size=42,
                text_color=(255, 255, 255, 255),
                stroke_width=0,
            ),
        )

        for effect in ("shadow", "glow", "outline", "relief"):
            with self.subTest(effect=effect):
                rendered = RenderService().render(
                    source,
                    request,
                    StyleSettings(
                        font_size=42,
                        text_color=(255, 255, 255, 255),
                        stroke_width=0,
                        effect=effect,
                    ),
                )
                self.assertIsNotNone(
                    ImageChops.difference(
                        rendered.convert("RGB"), plain.convert("RGB")
                    ).getbbox()
                )

    def test_caption_rotation_rotates_only_the_caption_layer(self):
        source = Image.new("RGB", (420, 260), "white")
        style = StyleSettings(font_size=48, text_color=(0, 0, 0, 255), stroke_width=0)
        plain = RenderService().render(
            source,
            [CaptionRenderRequest("Rotate", position_ratio=(0.5, 0.5))],
            style,
        )
        rotated = RenderService().render(
            source,
            [
                CaptionRenderRequest(
                    "Rotate", position_ratio=(0.5, 0.5), rotation=90.0
                )
            ],
            style,
        )

        plain_box = ImageChops.difference(plain.convert("RGB"), source).getbbox()
        rotated_box = ImageChops.difference(rotated.convert("RGB"), source).getbbox()
        self.assertIsNotNone(plain_box)
        self.assertIsNotNone(rotated_box)
        self.assertGreater(plain_box[2] - plain_box[0], plain_box[3] - plain_box[1])
        self.assertGreater(rotated_box[3] - rotated_box[1], rotated_box[2] - rotated_box[0])

    def test_selected_font_path_is_used_by_the_shared_renderer(self):
        font_path = next(
            (
                path
                for path in (
                    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
                    Path("C:/Windows/Fonts/consola.ttf"),
                )
                if path.exists()
            ),
            None,
        )
        if font_path is None:
            self.skipTest("系统中没有用于字体选择测试的字体")
        source = Image.new("RGB", (520, 260), "white")
        request = [CaptionRenderRequest("WWW iii", position_ratio=(0.5, 0.5))]
        default_render = RenderService().render(
            source,
            request,
            StyleSettings(font_size=54, text_color=(0, 0, 0, 255), stroke_width=0),
        )
        selected_font_render = RenderService().render(
            source,
            request,
            StyleSettings(
                font_size=54,
                font_path=str(font_path),
                text_color=(0, 0, 0, 255),
                stroke_width=0,
            ),
        )

        self.assertIsNotNone(
            ImageChops.difference(
                default_render.convert("RGB"), selected_font_render.convert("RGB")
            ).getbbox()
        )

    def test_long_caption_wraps_inside_the_image_safe_width(self):
        source = Image.new("RGB", (640, 360), "white")
        rendered = RenderService().render(
            source,
            [
                CaptionRenderRequest(
                    "没想到人间居然还能有这般强者，仅仅突破圣者数日便能与我抗衡",
                    position_ratio=(0.5, 0.72),
                )
            ],
            StyleSettings(
                font_size=48,
                text_color=(0, 0, 0, 255),
                stroke_width=0,
            ),
        )

        changed = ImageChops.difference(rendered.convert("RGB"), source).getbbox()
        self.assertIsNotNone(changed)
        self.assertLessEqual(changed[2] - changed[0], 580)
        self.assertGreater(changed[3] - changed[1], 70)



class ProportionalSizeTests(unittest.TestCase):
    """Spec 4.2: sizes follow the picture's short edge when the style names a reference edge."""

    SIZES = ((1080, 2340), (1920, 1080), (1280, 720), (1600, 1200), (3840, 2160))

    def share(self, style, size):
        geometry = RenderService().measure(size, [CaptionRenderRequest("测试字幕", (.5, .5))], style)[0]
        return geometry["height"] * size[1] / min(size)

    def test_same_share_of_short_edge(self):
        # Spec 6: within 1 %; each layer box is rounded up to whole pixels, so two boxes may differ by under 2 px.
        for look in ({}, {"show_background": True}, {"effect": "shadow"}):
            style = StyleSettings(font_size=54, stroke_width=2, font_path=str(NOTO_SANS), reference_edge=1080, **look)
            share = self.share(style, (1920, 1080))
            for size in self.SIZES:
                with self.subTest(look=look, size=size):
                    expected = share * min(size)
                    self.assertLessEqual(abs(self.share(style, size) * min(size) - expected), max(2, expected * .01))

    def test_pixel_style_unchanged(self):
        style = StyleSettings(font_size=54, stroke_width=2, font_path=str(NOTO_SANS))
        small, large = (RenderService().measure(size, [CaptionRenderRequest("测试字幕", (.5, .5))], style)[0] for size in ((1280, 720), (3840, 2160)))
        self.assertEqual(round(small["height"] * 720), round(large["height"] * 2160))

    def test_fractional_values_render(self):
        style = StyleSettings(font_size=54.5, stroke_width=1.33, line_spacing=6.67, letter_spacing=-.5, font_path=str(NOTO_SANS), reference_edge=1080)
        rendered = RenderService().render(Image.new("RGB", (1280, 720), "white"), [CaptionRenderRequest("测试字幕\n第二行", (.5, .8))], style)
        self.assertEqual((1280, 720), rendered.size)

    def test_scaled_style_leaves_pixel_styles_alone(self):
        style = StyleSettings(font_size=54)
        self.assertIs(style, scaled_style(style, (1280, 720)))
        proportional = StyleSettings(font_size=54, stroke_width=2, line_spacing=10, letter_spacing=3, reference_edge=1080)
        scaled = scaled_style(proportional, (1280, 720))
        for expected, actual in zip((36, 2 * 720 / 1080, 10 * 720 / 1080, 3 * 720 / 1080), (scaled.font_size, scaled.stroke_width, scaled.line_spacing, scaled.letter_spacing)):
            self.assertAlmostEqual(expected, actual)
        self.assertIs(proportional, scaled_style(proportional, (0, 0)))


if __name__ == "__main__":
    unittest.main()
