"""R4 backend: field-level batch edits, image sizes, background import, font name previews, window theme."""
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from subtitle_app import desktop
from subtitle_app.import_service import ImportService
from subtitle_app.web_controller import WebController
from subtitle_app.web_fonts import default_font_id, font_entries


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.c = WebController(self.root / "data")

    def tearDown(self):
        deadline = time.monotonic() + 10
        while (self.c.import_running or self.c.batch_running) and time.monotonic() < deadline:
            time.sleep(.01)
        self.temp.cleanup()

    def image(self, name, size=(320, 180), **save):
        path = self.source / name
        Image.new("RGB", size, "white").save(path, **save)
        return path

    def call(self, action, payload=None):
        p = self.c.project
        request = {"action": action, "payload": payload or {}, "requestId": uuid4().hex}
        if p:
            request.update(projectId=p.id, expectedRevision=p.revision)
        return self.c.dispatch(request)

    def ok(self, action, payload=None):
        reply = self.call(action, payload)
        self.assertTrue(reply["ok"], reply)
        return reply["result"]


class BatchSetTests(ControllerCase):
    def setUp(self):
        super().setUp()
        captions = ("这条巷子晚上很有味道", "我常在这里等朋友", "车站这边总是很多人", "我觉得变化不算大")
        self.c.import_paths([self.image(f"{text}.png", size=(1280, 720)) for text in captions])
        self.a, self.b, self.cc, self.d = (a.id for a in self.c.project.assets)
        for asset_id in (self.a, self.b, self.cc):
            caption = self.ok("caption_add", {"assetId": asset_id})["captionId"]
            self.ok("caption_text", {"assetId": asset_id, "captionId": caption, "text": "第二条"})
        for asset_id, size in ((self.a, 30), (self.b, 40), (self.cc, 50)):
            first = self.asset(asset_id).subtitles[0].id
            self.ok("caption_style", {"assetId": asset_id, "captionId": first, "style": {"font_size": size}})

    def asset(self, asset_id):
        return next(a for a in self.c.project.assets if a.id == asset_id)

    def style(self, asset_id, index):
        return self.c._style(self.asset(asset_id).subtitles[index])

    def test_writes_only_the_changed_field_of_that_caption_on_each_image(self):
        result = self.ok("batch_set", {"assetIds": [self.a, self.b], "captions": 0, "style": {"text_color": [255, 0, 0, 255]}})
        self.assertEqual([self.a, self.b], result["updated"])
        self.assertEqual((255, 0, 0, 255), tuple(self.style(self.a, 0)["text_color"]))
        self.assertEqual((255, 0, 0, 255), tuple(self.style(self.b, 0)["text_color"]))
        # Not a copy of one caption onto the others: each keeps its own size.
        self.assertEqual((30, 40), (self.style(self.a, 0)["font_size"], self.style(self.b, 0)["font_size"]))
        self.assertNotEqual((255, 0, 0, 255), tuple(self.style(self.a, 1)["text_color"]))
        self.assertNotEqual((255, 0, 0, 255), tuple(self.style(self.cc, 0)["text_color"]))

    def test_one_undo_reverts_the_whole_batch(self):
        depth = len(self.c.undo)
        self.ok("batch_set", {"assetIds": [self.a, self.b, self.cc], "captions": "all", "style": {"skew": 12}})
        self.assertEqual(depth + 1, len(self.c.undo))
        self.ok("undo")
        self.assertTrue(all(self.style(i, n)["skew"] == 0 for i in (self.a, self.b, self.cc) for n in (0, 1)))

    def test_images_without_that_caption_are_skipped_and_counted(self):
        result = self.ok("batch_set", {"assetIds": [self.a, self.d], "captions": 1, "style": {"font_size": 64}})
        self.assertEqual([self.a], result["updated"])
        self.assertEqual([self.d], [s["id"] for s in result["skipped"]])
        self.assertEqual(64, self.style(self.a, 1)["font_size"])

    def test_all_captions_scope_reaches_every_caption(self):
        self.ok("batch_set", {"assetIds": [self.a, self.b], "captions": "all", "style": {"alignment": "left"}})
        self.assertEqual(["left"] * 4, [self.style(i, n)["alignment"] for i in (self.a, self.b) for n in (0, 1)])

    def test_one_position_cannot_be_given_to_every_caption(self):
        reply = self.call("batch_set", {"assetIds": [self.a, self.b], "captions": "all", "position": {"x": .3}})
        self.assertEqual("POSITION_SCOPE", reply["error"]["code"])
        self.ok("batch_set", {"assetIds": [self.a, self.b], "captions": "all", "position": {"rotation": 5}})
        self.assertEqual(5, self.asset(self.b).subtitles[1].rotation)

    def test_a_position_axis_moves_only_that_axis(self):
        self.ok("caption_position", {"assetId": self.b, "captionId": self.asset(self.b).subtitles[0].id, "x": .5, "y": .2})
        self.ok("batch_set", {"assetIds": [self.a, self.b], "captions": 0, "position": {"x": .25}})
        self.assertEqual((.25, .2), self.asset(self.b).subtitles[0].manual_position_ratio)
        self.assertEqual(.25, self.asset(self.a).subtitles[0].manual_position_ratio[0])

    def test_speaker_applies_to_the_captions_in_scope(self):
        self.ok("batch_set", {"assetIds": [self.a, self.b], "captions": 1, "speaker": "小林"})
        self.assertEqual(["小林", "小林"], [self.asset(i).subtitles[1].speaker_id for i in (self.a, self.b)])
        self.assertIsNone(self.asset(self.a).subtitles[0].speaker_id)
        self.assertIn("小林", self.c.project.speakers)

    def test_an_invalid_value_changes_nothing(self):
        revision = self.c.project.revision
        reply = self.call("batch_set", {"assetIds": [self.a], "captions": 0, "style": {"font_size": 9999}})
        self.assertEqual("INVALID_INPUT", reply["error"]["code"])
        self.assertEqual(revision, self.c.project.revision)

    def test_nothing_to_change_is_rejected(self):
        self.assertEqual("EMPTY_SCOPE", self.call("batch_set", {"assetIds": [self.a], "captions": 0})["error"]["code"])

    def test_a_preset_applies_to_each_caption_by_its_own_size(self):
        self.ok("batch_set", {"assetIds": [self.a, self.b], "captions": 0, "preset": "粗描边斜体"})
        # The outline is a share of each caption's own font size (0.195 em), not one copied pixel width.
        self.assertEqual((round(30 * .195), round(40 * .195)), (self.style(self.a, 0)["stroke_width"], self.style(self.b, 0)["stroke_width"]))
        self.assertEqual((19, 19), (self.style(self.a, 0)["skew"], self.style(self.b, 0)["skew"]))
        self.assertEqual(0, self.style(self.a, 1)["skew"])

    def test_an_unknown_preset_changes_nothing(self):
        self.assertEqual("PRESET_MISSING", self.call("batch_set", {"assetIds": [self.a], "captions": 0, "preset": "没有这个"})["error"]["code"])

    def test_smart_layout_for_the_selection_clears_manual_positions(self):
        first = self.asset(self.a).subtitles[0].id
        self.ok("caption_position", {"assetId": self.a, "captionId": first, "x": .5, "y": .2})
        self.ok("batch_set", {"assetIds": [self.a, self.b], "captions": 0, "layout": "auto"})
        self.assertIsNone(self.asset(self.a).subtitles[0].manual_position_ratio)


class ImageSizeTests(ControllerCase):
    def test_import_records_the_upright_size(self):
        exif = Image.Exif()
        exif[274] = 6  # Rotated 90°: a 64×32 sensor image is shown 32 wide, 64 tall.
        path = self.image("竖拍.jpg", size=(64, 32), exif=exif)
        self.c.import_paths([path])
        asset = self.c.snapshot()["project"]["assets"][0]
        self.assertEqual((32, 64), (asset["width"], asset["height"]))

    def test_sizes_survive_saving_and_reopening(self):
        self.c.import_paths([self.image("横图.png", size=(300, 100))])
        reopened = WebController(self.root / "data")
        reopened.open_project(self.c.project_path)
        self.assertEqual((300, 100), (reopened.project.assets[0].width, reopened.project.assets[0].height))

    def test_projects_saved_without_sizes_get_them_on_open(self):
        self.c.import_paths([self.image("旧项目.png", size=(120, 90))])
        data = json.loads(self.c.project_path.read_text(encoding="utf-8"))
        for asset in data["assets"]:
            del asset["width"], asset["height"]
        self.c.project_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        reopened = WebController(self.root / "data")
        reopened.open_project(self.c.project_path)
        self.assertEqual((120, 90), (reopened.project.assets[0].width, reopened.project.assets[0].height))


class ImportTaskTests(ControllerCase):
    """Choosing images returns at once; reading them happens behind a progress report."""

    def setUp(self):
        super().setUp()
        self.paths = [self.image(f"画面{i}.png") for i in range(5)]
        self.c.native = lambda action, p: [str(x) for x in self.paths] if action == "choose_images" else None
        # Each chunk read waits for one permit, so the test decides exactly how far the import gets.
        self.permits = threading.Semaphore(0)
        self.reads = []
        original = ImportService.import_paths

        def gated(service, paths):
            self.reads.append(len(paths))
            self.permits.acquire(timeout=10)
            return original(service, paths)

        patcher = patch.object(ImportService, "import_paths", gated)
        patcher.start()
        self.addCleanup(patcher.stop)
        chunk = patch.object(WebController, "IMPORT_CHUNK", 2)
        chunk.start()
        self.addCleanup(chunk.stop)
        self.addCleanup(self.release, 10)

    def release(self, count):
        for _ in range(count):
            self.permits.release()

    def task(self):
        return self.c.snapshot()["importTask"]

    def wait(self, condition):
        deadline = time.monotonic() + 10
        while not condition() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(condition())

    def test_choosing_images_returns_at_once_and_reports_progress(self):
        result = self.ok("choose_images")
        self.assertTrue(result["started"])
        self.assertEqual(5, result["total"])
        self.wait(lambda: len(self.reads) == 1)
        task = self.task()
        self.assertEqual(("running", 0, 5), (task["state"], task["completed"], task["total"]))
        self.release(3)
        self.wait(lambda: self.task()["state"] == "complete")
        self.assertEqual(5, len(self.c.project.assets))
        self.assertEqual(5, self.task()["result"]["imported"])

    def test_pictures_appear_chunk_by_chunk(self):
        self.ok("choose_images")
        self.release(1)
        self.wait(lambda: len(self.reads) == 2)
        self.assertEqual(2, len(self.c.project.assets))
        self.assertEqual(2, self.task()["completed"])
        self.release(2)
        self.wait(lambda: self.task()["state"] == "complete")

    def test_editing_waits_for_the_import(self):
        self.ok("choose_images")
        self.wait(lambda: len(self.reads) == 1)
        self.assertEqual("IMPORT_BUSY", self.call("rename", {"name": "改名"})["error"]["code"])
        self.release(3)
        self.wait(lambda: self.task()["state"] == "complete")
        self.ok("rename", {"name": "改名"})

    def test_one_undo_removes_the_whole_import(self):
        self.ok("choose_images")
        self.release(3)
        self.wait(lambda: self.task()["state"] == "complete")
        self.ok("undo")
        self.assertEqual([], self.c.project.assets)

    def test_cancelling_keeps_what_was_already_read(self):
        task_id = self.ok("choose_images")["taskId"]
        self.release(1)
        self.wait(lambda: len(self.reads) == 2)
        self.ok("cancel_import", {"taskId": task_id})
        self.release(1)
        self.wait(lambda: self.task()["state"] == "cancelled")
        self.assertEqual(2, len(self.c.project.assets))
        self.ok("dismiss_import", {"taskId": task_id})
        self.assertIsNone(self.task())

    def test_a_file_that_cannot_be_imported_does_not_stop_the_rest(self):
        bad = self.source / "说明.txt"
        bad.write_text("不是图片", encoding="utf-8")
        self.paths.insert(1, bad)
        self.ok("choose_images")
        self.release(3)
        self.wait(lambda: self.task()["state"] == "complete")
        self.assertEqual(5, len(self.c.project.assets))
        self.assertEqual(["说明.txt"], [issue["file"] for issue in self.c.snapshot()["issues"]])
        self.assertEqual(1, self.task()["result"]["issues"])


class FontPreviewTests(ControllerCase):
    def test_a_font_name_is_drawn_in_its_own_face(self):
        reply = self.c.dispatch({"action": "font_preview", "payload": {"fontId": default_font_id()}})
        self.assertTrue(reply["ok"], reply)
        with Image.open(io.BytesIO(self.c.media_bytes(reply["result"]["token"]))) as image:
            self.assertEqual("RGBA", image.mode)
            self.assertGreater(image.getchannel("A").getextrema()[1], 200)
            self.assertLessEqual(image.height, 64)

    def test_a_font_that_cannot_draw_its_own_name_is_shown_as_text(self):
        entry = dict(font_entries()[default_font_id()], label="ツ字")
        with patch("subtitle_app.web_controller.font_entries", return_value={"x": entry}), \
                patch("subtitle_app.web_controller.font_codepoints", return_value=frozenset(map(ord, "字"))):
            reply = self.c.dispatch({"action": "font_preview", "payload": {"fontId": "x"}})
        self.assertEqual("FONT_PREVIEW_UNAVAILABLE", reply["error"]["code"])

    def test_an_unknown_font_is_reported(self):
        reply = self.c.dispatch({"action": "font_preview", "payload": {"fontId": "不存在"}})
        self.assertEqual("FONT_MISSING", reply["error"]["code"])


class PreflightRevisionTests(ControllerCase):
    def test_a_check_made_before_an_edit_cannot_start_the_export(self):
        self.c.import_paths([self.image("确认.png")])
        asset = self.c.project.assets[0]
        self.ok("confirm", {"assetId": asset.id})
        self.c.outputs["out"] = self.root / "out"
        check = self.ok("preflight", {"outputToken": "out"})
        self.assertEqual(self.c.project.revision, check["revision"])
        self.ok("rename", {"name": "改过的项目"})
        reply = self.call("start_export", {"preflightId": check["id"], "acknowledge": True})
        self.assertEqual("PREFLIGHT_EXPIRED", reply["error"]["code"])


class AppIconTests(unittest.TestCase):
    def test_the_icon_carries_every_windows_size(self):
        with Image.open(Path(desktop.__file__).parent / "resources" / "app.ico") as icon:
            self.assertEqual({(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)}, set(icon.info["sizes"]))


class PreflightOutputTests(ControllerCase):
    def test_each_planned_file_names_the_picture_it_comes_from(self):
        self.c.import_paths([self.image(f"{text}.png") for text in ("第一句话", "第二句话")])
        for asset in self.c.project.assets:
            self.ok("confirm", {"assetId": asset.id})
        self.c.outputs["out"] = self.root / "out"
        check = self.ok("preflight", {"outputToken": "out", "naming": "sequence", "prefix": "片段_"})
        self.assertEqual([(a.id, f"片段_{i + 1:02d}.png") for i, a in enumerate(self.c.project.assets)],
                         [(o["assetId"], o["file"]) for o in check["outputs"]])


class SpeakerListTests(ControllerCase):
    def test_names_can_be_added_and_removed_without_a_caption(self):
        self.c.import_paths([self.image("说话人.png")])
        self.ok("speakers", {"operation": "add", "name": " 小林 "})
        self.ok("speakers", {"operation": "add", "name": "小林"})
        self.assertEqual(["小林"], self.c.project.speakers)
        self.ok("speakers", {"operation": "remove", "name": "小林"})
        self.assertEqual([], self.c.project.speakers)
        self.ok("undo")
        self.assertEqual(["小林"], self.c.project.speakers)


class PresetDefaultTests(ControllerCase):
    def test_choosing_the_builtin_look_clears_the_saved_default(self):
        self.c.import_paths([self.image("样式.png")])
        asset = self.c.project.assets[0]
        self.ok("preset", {"operation": "save", "name": "采访白字", "assetId": asset.id, "captionId": asset.subtitles[0].id})
        self.ok("preset", {"operation": "default", "name": "采访白字"})
        self.assertEqual("采访白字", self.c.snapshot()["defaultPreset"])
        self.ok("preset", {"operation": "default", "name": "经典"})
        self.assertIsNone(self.c.snapshot()["defaultPreset"])


class WindowThemeTests(unittest.TestCase):
    def test_the_window_opens_in_the_system_theme_colour(self):
        self.assertEqual("#1E1E1E", desktop.window_background(True))
        self.assertEqual("#F5F5F5", desktop.window_background(False))

    def test_macos_dark_appearance_is_detected(self):
        dark = subprocess.CompletedProcess([], 0, stdout="Dark\n")
        with patch.object(desktop.subprocess, "run", return_value=dark):
            self.assertTrue(desktop.prefers_dark("darwin"))
        with patch.object(desktop.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "defaults")):
            self.assertFalse(desktop.prefers_dark("darwin"))

    def test_windows_app_theme_is_read_from_the_registry(self):
        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def registry(light):
            return types.SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=lambda *a: Key(), QueryValueEx=lambda key, name: (light, 4))

        with patch.dict(sys.modules, {"winreg": registry(0)}):
            self.assertTrue(desktop.prefers_dark("win32"))
        with patch.dict(sys.modules, {"winreg": registry(1)}):
            self.assertFalse(desktop.prefers_dark("win32"))


if __name__ == "__main__":
    unittest.main()
