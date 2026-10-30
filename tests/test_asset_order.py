"""Image order must follow when each picture was taken, because filenames are captions, not numbers."""
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from PIL import Image

from subtitle_app.asset_sorter import capture_time, file_times, order_assets, time_source, time_ties
from subtitle_app.filename_classifier import FilenameKind
from subtitle_app import import_service
from subtitle_app.import_service import ImportService
from subtitle_app.models import Asset, CaptionStatus
from subtitle_app.project_store import ProjectStore
from subtitle_app.web_controller import WebController

EPOCH = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)


def asset(name, *, created, modified, order, taken=None):
    return Asset(id=name, source_path=Path("/images") / name, filename=name,
                 created_at=EPOCH + timedelta(seconds=created), modified_at=EPOCH + timedelta(seconds=modified),
                 import_order=order, filename_kind=FilenameKind.CAPTION, caption_status=CaptionStatus.READY,
                 taken_at=None if taken is None else EPOCH + timedelta(seconds=taken))


def write_image(path: Path, modified: float, exif_original: str | None = None, subsec: str | None = None):
    image = Image.new("RGB", (32, 18), "white")
    if exif_original is None:
        image.save(path)
    else:
        exif = Image.Exif()
        exif.get_ifd(0x8769)[36867] = exif_original
        if subsec is not None:
            exif.get_ifd(0x8769)[37521] = subsec
        image.save(path, exif=exif)
    os.utime(path, (modified, modified))


class CaptureTimeTests(unittest.TestCase):
    def test_a_copied_file_is_dated_by_its_modification_time(self):
        # Explorer copies keep the modification time but stamp a new creation time.
        copied = asset("后来复制的.png", created=500, modified=10, order=0)
        self.assertEqual(EPOCH + timedelta(seconds=10), capture_time(copied))
        self.assertEqual("modified", time_source(copied))

    def test_an_edited_file_keeps_its_creation_time(self):
        edited = asset("裁剪过的.png", created=10, modified=900, order=0)
        self.assertEqual(EPOCH + timedelta(seconds=10), capture_time(edited))
        self.assertEqual("created", time_source(edited))

    def test_the_time_recorded_in_the_photo_wins_over_file_times(self):
        photo = asset("照片.jpg", created=500, modified=400, order=0, taken=5)
        self.assertEqual(EPOCH + timedelta(seconds=5), capture_time(photo))
        self.assertEqual("exif", time_source(photo))

    def test_windows_creation_time_comes_from_st_ctime_when_birthtime_is_absent(self):
        created, modified = file_times(SimpleNamespace(st_ctime=100.0, st_mtime=200.0), windows=True)
        self.assertEqual((100.0, 200.0), (created.timestamp(), modified.timestamp()))

    def test_other_systems_never_mistake_inode_change_time_for_creation(self):
        created, modified = file_times(SimpleNamespace(st_ctime=100.0, st_mtime=200.0), windows=False)
        self.assertEqual((200.0, 200.0), (created.timestamp(), modified.timestamp()))


class OrderTests(unittest.TestCase):
    def test_time_order_ignores_caption_like_filenames(self):
        assets = [asset("啊，终于到了.png", created=30, modified=30, order=0), asset("不要走.png", created=10, modified=10, order=1), asset("此时.png", created=20, modified=20, order=2)]
        self.assertEqual(["不要走.png", "此时.png", "啊，终于到了.png"], [a.filename for a in order_assets(assets, "time")])

    def test_files_with_the_same_time_fall_back_to_natural_filename_order(self):
        assets = [asset("画面 10.png", created=5, modified=5, order=0), asset("画面 9.png", created=5, modified=5, order=1), asset("画面 1.png", created=5, modified=5, order=2)]
        self.assertEqual(["画面 1.png", "画面 9.png", "画面 10.png"], [a.filename for a in order_assets(assets, "time")])
        self.assertEqual([{"画面 10.png", "画面 9.png", "画面 1.png"}], [set(group) for group in time_ties(assets)])

    def test_newest_first_reverses_time_order(self):
        assets = [asset("一.png", created=1, modified=1, order=0), asset("二.png", created=2, modified=2, order=1)]
        self.assertEqual(["二.png", "一.png"], [a.filename for a in order_assets(assets, "time_desc")])

    def test_manual_order_is_kept_as_is(self):
        assets = [asset("二.png", created=2, modified=2, order=1), asset("一.png", created=1, modified=1, order=0)]
        self.assertEqual(["二.png", "一.png"], [a.filename for a in order_assets(assets, "manual")])


class ImportTimeTests(unittest.TestCase):
    def test_import_reads_the_capture_time_stored_in_the_photo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "拍摄的照片.jpg"
            write_image(path, time.time(), "2026:08:25 10:18:35", "250")
            taken = ImportService().import_paths([path]).assets[0].taken_at
        self.assertEqual((2026, 8, 25, 10, 18, 35, 250000), (taken.year, taken.month, taken.day, taken.hour, taken.minute, taken.second, taken.microsecond))

    def test_import_ignores_an_implausible_camera_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "错误时钟.jpg"
            write_image(path, time.time(), "1970:01:01 00:00:00")
            self.assertIsNone(ImportService().import_paths([path]).assets[0].taken_at)

    def test_an_unset_camera_clock_never_reaches_time_zone_conversion(self):
        class WindowsDatetime(datetime):
            def astimezone(self, tz=None):
                if self.tzinfo is None and self.year < 1971:
                    raise OSError(22, "Invalid argument")  # Windows localtime() before 1970
                return super().astimezone(tz)
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(import_service, "datetime", WindowsDatetime):
            path = Path(directory) / "没设时钟.jpg"
            write_image(path, time.time(), "1970:01:01 00:00:00")
            self.assertIsNone(ImportService().import_paths([path]).assets[0].taken_at)


class ProjectOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        base = time.time() - 3600
        # Alphabetical order of these captions is the opposite of the order they were captured in.
        self.story = ["终于等到你", "你还记得吗", "啊，是你"]
        self.paths = []
        for minute, caption in enumerate(self.story):
            path = self.source / f"{caption}.png"
            write_image(path, base + minute * 60)
            self.paths.append(path)
        self.c = WebController(self.root / "data")

    def tearDown(self):
        self.temp.cleanup()

    def call(self, action, payload=None):
        p = self.c.project
        return self.c.dispatch({"action": action, "payload": payload or {}, "projectId": p.id, "expectedRevision": p.revision, "requestId": uuid4().hex})

    def names(self):
        return [a.filename.removesuffix(".png") for a in self.c.project.assets]

    def test_a_new_project_is_ordered_by_capture_time_not_by_filename(self):
        self.c.import_paths(sorted(self.paths))
        self.assertEqual(self.story, self.names())
        self.assertEqual("time", self.c.snapshot()["project"]["orderMode"])

    def test_sequence_export_numbers_follow_the_project_order(self):
        self.c.import_paths(sorted(self.paths))
        for a in self.c.project.assets:
            self.call("confirm", {"assetId": a.id})
        self.c.outputs["out"] = self.root / "out"
        files = self.call("preflight", {"outputToken": "out", "naming": "sequence", "start": 1, "digits": 2})["result"]["files"]
        self.assertEqual(["01.png", "02.png", "03.png"], [Path(f).name for f in files])
        self.assertEqual(self.story, self.names())

    def test_choosing_an_order_reorders_the_project_and_can_be_undone(self):
        self.c.import_paths(sorted(self.paths))
        self.assertTrue(self.call("set_order", {"mode": "filename"})["ok"])
        self.assertEqual(sorted(self.story), self.names())
        self.assertEqual("filename", self.c.snapshot()["project"]["orderMode"])
        self.call("undo")
        self.assertEqual(self.story, self.names())

    def test_dragging_an_image_switches_to_manual_order(self):
        self.c.import_paths(sorted(self.paths))
        ids = [a.id for a in self.c.project.assets]
        self.call("reorder_assets", {"assetIds": [ids[2], ids[0], ids[1]]})
        self.assertEqual("manual", self.c.snapshot()["project"]["orderMode"])
        self.c.import_paths([])
        self.assertEqual([self.story[2], self.story[0], self.story[1]], self.names())

    def test_images_added_to_a_time_ordered_project_take_their_place_in_time(self):
        self.c.import_paths([self.paths[0], self.paths[2]])
        self.c.import_paths([self.paths[1]])
        self.assertEqual(self.story, self.names())

    def test_images_added_to_a_manually_ordered_project_go_to_the_end(self):
        self.c.import_paths([self.paths[0], self.paths[2]])
        ids = [a.id for a in self.c.project.assets]
        self.call("reorder_assets", {"assetIds": list(reversed(ids))})
        self.c.import_paths([self.paths[1]])
        self.assertEqual([self.story[2], self.story[0], self.story[1]], self.names())

    def test_projects_saved_before_ordering_existed_keep_their_order(self):
        self.c.import_paths(sorted(self.paths))
        path = self.c.project_path
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["order_mode"]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertEqual("manual", ProjectStore().load(path).order_mode)

    def test_snapshot_explains_where_each_time_comes_from(self):
        self.c.import_paths(sorted(self.paths))
        first = self.c.snapshot()["project"]["assets"][0]
        self.assertIn(first["timeSource"], {"created", "modified"})
        self.assertIsNone(first["takenAt"])
        self.assertTrue(first["captureTime"])


if __name__ == "__main__":
    unittest.main()
