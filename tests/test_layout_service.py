import unittest
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from subtitle_app.layout_service import LayoutService


class LayoutServiceTests(unittest.TestCase):
    def test_joint_layout_keeps_order_and_avoids_fixed_captions(self):
        service = LayoutService()
        image = Image.new("RGB", (1000, 800), "white")
        sizes = [(360, 55), (520, 70), (220, 60)]
        fixed = (400, 600, 200, 100)
        result = service.arrange(service.analyze(image), sizes, [fixed])
        self.assertIsNotNone(result.positions)
        rects = [(round(x*image.width-w/2), round(y*image.height-h/2), w, h)
                 for (x, y), (w, h) in zip(result.positions, sizes)]
        for index, rect in enumerate(rects):
            self.assertEqual(0, service._intersection_area(rect, fixed))
            if index:
                self.assertLess(rects[index-1][1] + rects[index-1][3], rect[1])

    def test_twenty_captions_can_be_arranged_without_reusing_positions(self):
        service = LayoutService()
        analysis = service.analyze(Image.new("RGB", (1000, 1600), "white"))
        result = service.arrange(analysis, [(400, 30)] * 20)
        self.assertIsNotNone(result.positions)
        self.assertEqual(20, len(set(result.positions)))
        self.assertEqual(sorted(p[1] for p in result.positions), [p[1] for p in result.positions])

    def test_insufficient_space_returns_no_partial_layout(self):
        service = LayoutService()
        analysis = service.analyze(Image.new("RGB", (500, 300)))
        self.assertIsNone(service.arrange(analysis, [(350, 150)] * 3).positions)
        self.assertIsNone(service.arrange(analysis, [(501, 40)]).positions)

    def test_background_detail_can_outweigh_bottom_preference(self):
        image = Image.new("RGB", (640, 480), "white")
        draw = ImageDraw.Draw(image)
        for x in range(0, 640, 24):
            draw.rectangle((x, 240, x+11, 480), fill="black")
        service = LayoutService()
        result = service.arrange(service.analyze(image), [(320, 80)])
        self.assertIsNotNone(result.positions)
        self.assertLess(result.positions[0][1]*480 + 40, 240)

    def test_people_fallback_reports_overlap_but_never_overlaps_captions(self):
        service = LayoutService()
        analysis = service.analyze(Image.new("RGB", (640, 480)), [(0, 0, 640, 480)])
        result = service.arrange(analysis, [(300, 50)] * 2)
        self.assertTrue(result.overlaps_people)
        self.assertGreater(result.positions[1][1] - result.positions[0][1], 50/480)

    def test_completely_off_canvas_fixed_caption_does_not_mask_the_image(self):
        service = LayoutService()
        analysis = service.analyze(Image.new("RGB", (640, 480)))
        result = service.arrange(analysis, [(300, 50)], [(-100, -100, 20, 20)])
        self.assertIsNotNone(result.positions)

    def test_analysis_cache_is_bounded_after_more_than_one_thousand_sources(self):
        service = LayoutService()
        calls = 0
        def detect(_):
            nonlocal calls
            calls += 1
            return []
        service.detect_protected_regions = detect
        with tempfile.TemporaryDirectory() as directory:
            image = Image.new("RGB", (320, 320), "white")
            for index in range(1001):
                path = Path(directory) / f"{index}.png"
                image.save(path)
                last = service.analyze_path(path)
            self.assertIs(last, service.analyze_path(path))
            self.assertEqual(1001, calls)
            self.assertLessEqual(len(service._cache), service.CACHE_ENTRIES)
            self.assertLessEqual(service._cache_bytes, service.CACHE_BYTES)
            image.resize((160, 320)).save(path)
            self.assertEqual((160, 320), service.analyze_path(path).image_size)
            self.assertEqual(1002, calls)

    def test_auto_position_avoids_a_protected_face_region(self):
        image = Image.new("RGB", (1000, 600), "white")
        face_region = (350, 360, 300, 190)

        position = LayoutService().choose_position(
            image,
            text_size=(320, 90),
            protected_regions=[face_region],
        )

        text_left = position[0] * image.width - 160
        text_top = position[1] * image.height - 45
        text_right = text_left + 320
        text_bottom = text_top + 90
        face_left, face_top, face_width, face_height = face_region
        overlaps = not (
            text_right <= face_left
            or text_left >= face_left + face_width
            or text_bottom <= face_top
            or text_top >= face_top + face_height
        )
        self.assertFalse(overlaps)


if __name__ == "__main__":
    unittest.main()
