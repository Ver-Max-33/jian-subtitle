import tempfile
import unittest
from pathlib import Path

from PIL import Image

from subtitle_app.export_job import ExportJobRunner
from subtitle_app.models import (
    CaptionRenderRequest,
    ExportJobItem,
    JobItemStatus,
    StyleSettings,
)


class ExportJobRunnerTests(unittest.TestCase):
    def test_one_failed_file_does_not_stop_the_remaining_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good_source = root / "good.png"
            Image.new("RGB", (100, 80), "white").save(good_source)
            items = [
                ExportJobItem(
                    source_path=root / "missing.png",
                    output_path=root / "out" / "missing.png",
                    captions=[CaptionRenderRequest("Missing")],
                    style=StyleSettings(font_size=16),
                ),
                ExportJobItem(
                    source_path=good_source,
                    output_path=root / "out" / "good.png",
                    captions=[CaptionRenderRequest("Good")],
                    style=StyleSettings(font_size=16, text_color=(0, 0, 0, 255)),
                ),
            ]

            result = ExportJobRunner().run(items)

            self.assertEqual(1, result.success_count)
            self.assertEqual(1, result.failed_count)
            self.assertEqual(JobItemStatus.FAILED, result.items[0].status)
            self.assertEqual(JobItemStatus.SUCCESS, result.items[1].status)
            self.assertTrue((root / "out" / "good.png").exists())

    def test_progress_reports_each_completed_item_including_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good_source = root / "good.png"
            Image.new("RGB", (80, 60), "white").save(good_source)
            items = [
                ExportJobItem(
                    root / "missing.png",
                    root / "out" / "missing.png",
                    [CaptionRenderRequest("Missing")],
                    StyleSettings(font_size=14),
                ),
                ExportJobItem(
                    good_source,
                    root / "out" / "good.png",
                    [CaptionRenderRequest("Good")],
                    StyleSettings(font_size=14),
                ),
            ]
            progress: list[tuple[int, int, JobItemStatus]] = []

            ExportJobRunner().run(
                items,
                on_progress=lambda completed, total, item: progress.append(
                    (completed, total, item.status)
                ),
            )

        self.assertEqual(
            [
                (1, 2, JobItemStatus.FAILED),
                (2, 2, JobItemStatus.SUCCESS),
            ],
            progress,
        )

    def test_no_caption_copy_preserves_the_original_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "plain.png"
            output = root / "out" / "plain.png"
            Image.new("RGB", (73, 51), (23, 45, 67)).save(source, compress_level=9)
            original_bytes = source.read_bytes()
            item = ExportJobItem(
                source,
                output,
                [],
                StyleSettings(),
                copy_original=True,
            )

            result = ExportJobRunner().run([item])

            self.assertEqual(1, result.success_count)
            self.assertEqual(original_bytes, output.read_bytes())

    def test_cancellation_marks_remaining_items_as_retryable_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            items = []
            for index in range(3):
                source = root / f"source-{index}.png"
                Image.new("RGB", (60, 40), "white").save(source)
                items.append(
                    ExportJobItem(
                        source,
                        root / "out" / f"result-{index}.png",
                        [CaptionRenderRequest(str(index))],
                        StyleSettings(font_size=12),
                    )
                )
            cancelled = False

            def on_progress(completed, total, item):
                nonlocal cancelled
                cancelled = True

            result = ExportJobRunner().run(
                items,
                is_cancelled=lambda: cancelled,
                on_progress=on_progress,
            )

        self.assertTrue(result.cancelled)
        self.assertEqual(1, result.success_count)
        self.assertEqual(2, result.skipped_count)
        self.assertEqual(
            [JobItemStatus.SUCCESS, JobItemStatus.SKIPPED, JobItemStatus.SKIPPED],
            [item.status for item in result.items],
        )


if __name__ == "__main__":
    unittest.main()
