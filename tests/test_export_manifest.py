import tempfile
import unittest
from pathlib import Path

from subtitle_app.export_manifest import ExportManifestStore
from subtitle_app.models import (
    CaptionRenderRequest,
    ExportJobItem,
    JobItemStatus,
    StyleSettings,
)


class ExportManifestStoreTests(unittest.TestCase):
    def test_manifest_restores_only_failed_or_unfinished_items_with_same_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            items = [
                ExportJobItem(
                    root / "done.png",
                    root / "out" / "done.png",
                    [CaptionRenderRequest("完成")],
                    StyleSettings(font_size=24),
                    status=JobItemStatus.SUCCESS,
                ),
                ExportJobItem(
                    root / "later.png",
                    root / "out" / "fixed-name.png",
                    [CaptionRenderRequest("继续", (0.3, 0.7), 4.0)],
                    StyleSettings(font_size=32),
                    preserve_metadata=False,
                    status=JobItemStatus.SKIPPED,
                ),
            ]
            path = root / "task.json"
            store = ExportManifestStore()

            store.save(items, path, cancelled=True)
            resumed = store.load_incomplete(path)

        self.assertEqual(1, len(resumed.items))
        item = resumed.items[0]
        self.assertEqual("fixed-name.png", item.output_path.name)
        self.assertEqual("继续", item.captions[0].text)
        self.assertEqual((0.3, 0.7), item.captions[0].position_ratio)
        self.assertEqual(JobItemStatus.PENDING, item.status)
        self.assertFalse(item.preserve_metadata)


if __name__ == "__main__":
    unittest.main()
