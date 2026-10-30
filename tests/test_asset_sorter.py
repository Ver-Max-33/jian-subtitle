import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from subtitle_app.asset_sorter import AssetSortMode, sorted_assets
from subtitle_app.filename_classifier import FilenameKind
from subtitle_app.models import Asset, CaptionStatus


def make_asset(
    filename: str,
    *,
    created_offset: int,
    modified_offset: int,
    import_order: int,
) -> Asset:
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Asset(
        id=filename,
        source_path=Path("/images") / filename,
        filename=filename,
        created_at=epoch + timedelta(seconds=created_offset),
        modified_at=epoch + timedelta(seconds=modified_offset),
        import_order=import_order,
        filename_kind=FilenameKind.CAPTION,
        caption_status=CaptionStatus.READY,
    )


class AssetSorterTests(unittest.TestCase):
    def setUp(self):
        self.assets = [
            make_asset("b.png", created_offset=20, modified_offset=10, import_order=0),
            make_asset("a.png", created_offset=10, modified_offset=30, import_order=1),
            make_asset("c.png", created_offset=10, modified_offset=20, import_order=2),
        ]

    def test_creation_time_sort_is_stable_for_equal_timestamps(self):
        result = sorted_assets(self.assets, AssetSortMode.CREATED)
        self.assertEqual(["a.png", "c.png", "b.png"], [item.filename for item in result])

    def test_other_user_visible_sort_modes_have_deterministic_results(self):
        self.assertEqual(
            ["b.png", "c.png", "a.png"],
            [item.filename for item in sorted_assets(self.assets, AssetSortMode.MODIFIED)],
        )
        self.assertEqual(
            ["a.png", "b.png", "c.png"],
            [item.filename for item in sorted_assets(self.assets, AssetSortMode.FILENAME)],
        )
        self.assertEqual(
            ["b.png", "a.png", "c.png"],
            [item.filename for item in sorted_assets(self.assets, AssetSortMode.IMPORT_ORDER)],
        )


if __name__ == "__main__":
    unittest.main()
