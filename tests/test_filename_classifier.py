import unittest

from subtitle_app.filename_classifier import FilenameClassifier, FilenameKind


class FilenameClassifierTests(unittest.TestCase):
    def test_chinese_filename_becomes_an_automatic_caption(self):
        result = FilenameClassifier().classify(
            "没想到人间居然还能有这般强者，仅仅突破圣者数日便能与我抗衡.png"
        )

        self.assertEqual(FilenameKind.CAPTION, result.kind)
        self.assertEqual(
            "没想到人间居然还能有这般强者，仅仅突破圣者数日便能与我抗衡",
            result.caption_text,
        )

    def test_timestamp_filename_is_not_treated_as_a_caption(self):
        result = FilenameClassifier().classify("20260121_021602.png")

        self.assertEqual(FilenameKind.TIMESTAMP_OR_SEQUENCE, result.kind)
        self.assertIsNone(result.caption_text)

    def test_common_timestamp_and_camera_sequence_names_are_not_captions(self):
        filenames = (
            "2026-01-21 02-16-02.jpg",
            "20260121.png",
            "000123.png",
            "IMG_0123.jpg",
            "DSC_0123.jpg",
            "PXL_20260121_021602.jpg",
        )

        for filename in filenames:
            with self.subTest(filename=filename):
                result = FilenameClassifier().classify(filename)
                self.assertEqual(FilenameKind.TIMESTAMP_OR_SEQUENCE, result.kind)
                self.assertIsNone(result.caption_text)


if __name__ == "__main__":
    unittest.main()
