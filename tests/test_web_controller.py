import copy
import math
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from PIL import Image

from subtitle_app.models import CaptionStatus, StyleSettings
from subtitle_app.web_controller import WebController
from subtitle_app.web_contracts import CommandError, style_patch, windows_filename
from subtitle_app.export_service import ExportService
from subtitle_app.export_planner import ExportPlanner
from subtitle_app.render_service import RenderService


class WebControllerTests(unittest.TestCase):
    def test_large_batch_can_be_cancelled_without_partial_changes(self):
        source = self.controller.project.assets[0]
        for index in range(33):
            asset = copy.deepcopy(source)
            asset.id = uuid4().hex
            asset.filename = f"Batch {index}.png"
            self.controller.project.assets.append(asset)
        before = copy.deepcopy(self.controller.project)
        started, release = threading.Event(), threading.Event()
        def block_layout(*args):
            started.set()
            release.wait(5)
            return {"placed": True, "warning": None}
        with patch.object(self.controller, "_layout_asset", side_effect=block_layout):
            try:
                reply = self.request("batch_style", {**self.scope(), "assetIds": [a.id for a in before.assets],
                                                      "position": True, "style": True})
                self.assertTrue(reply["result"]["started"])
                self.assertTrue(started.wait(5))
                denied = self.request("caption_text", {**self.scope(), "text": "Must not change"})
                self.assertEqual("BATCH_BUSY", denied["error"]["code"])
                self.request("cancel_batch", {"taskId": reply["result"]["taskId"]})
            finally:
                release.set()
                deadline = time.monotonic() + 5
                while self.controller.batch_running and time.monotonic() < deadline:
                    time.sleep(.01)
        self.assertEqual("cancelled", self.controller.batch_task["state"])
        self.assertEqual(before, self.controller.project)

    def test_batch_does_not_copy_one_manual_position_to_all_captions(self):
        self.request("caption_position", {**self.scope(), "x": .5, "y": .5})
        before = copy.deepcopy(self.controller.project)
        result = self.request("batch_style", {**self.scope(), "assetIds": [a.id for a in before.assets],
                                              "position": True, "allCaptions": True})
        self.assertEqual("POSITION_SCOPE", result["error"]["code"])
        self.assertEqual(before, self.controller.project)

    def test_smart_layout_arranges_automatic_captions_and_preserves_other_manual_positions(self):
        scope = self.scope()
        asset_id = scope["assetId"]
        second = self.request("caption_add", {"assetId": asset_id})["result"]["captionId"]
        third = self.request("caption_add", {"assetId": asset_id})["result"]["captionId"]
        for caption_id in (scope["captionId"], second, third):
            self.request("caption_text", {"assetId": asset_id, "captionId": caption_id, "text": "Some text"})
            self.request("caption_style", {"assetId": asset_id, "captionId": caption_id, "style": {"font_size": 24}})
        self.request("caption_position", {"assetId": asset_id, "captionId": third, "x": .5, "y": .8})
        before = copy.deepcopy(self.controller.project)
        with patch.object(self.controller.layout, "detect_protected_regions", return_value=[]) as detector:
            result = self.request("smart_layout", scope)
            self.assertTrue(result["ok"], result)
            self.assertEqual(2, result["result"]["count"])
            self.request("smart_layout", scope)
            self.assertEqual(1, detector.call_count)
        asset = self.controller.project.assets[0]
        self.assertEqual(before.assets[0].subtitles[2].manual_position_ratio, asset.subtitles[2].manual_position_ratio)
        style = StyleSettings.from_mapping(self.controller.project.default_style)
        geometry = RenderService().measure((640, 360), ExportPlanner.caption_requests(asset, style), style)
        for i, first in enumerate(geometry):
            x1, y1, x2, y2 = first["bounds"]
            for other in geometry[i+1:]:
                a, b, c, d = other["bounds"]
                self.assertFalse(min(x2, c) > max(x1, a) and min(y2, d) > max(y1, b))
        self.request("undo")
        self.assertEqual(before.assets, self.controller.project.assets)

    def test_failed_smart_layout_keeps_manual_mode_and_position(self):
        scope = self.scope()
        self.request("caption_text", {**scope, "text": "Long subtitle\n" * 20})
        self.request("caption_position", {**scope, "x": .4, "y": .5, "rotation": 32})
        before = copy.deepcopy(self.controller.project)
        with patch.object(self.controller.layout, "detect_protected_regions", return_value=[]):
            result = self.request("smart_layout", scope)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"]["placed"])
        self.assertEqual(before, self.controller.project)

    def test_state_poll_omits_unchanged_project_and_edit_returns_fresh_project(self):
        project = self.controller.project
        known = {"knownProjectId": project.id, "knownRevision": project.revision, "knownPath": str(self.controller.project_path)}
        state = self.request("state", known)["result"]
        self.assertTrue(state["projectUnchanged"])
        self.assertIsNone(state["project"])
        changed = self.request("caption_text", {**self.scope(), "text": "Changed"})
        self.assertEqual("Changed", changed["state"]["project"]["assets"][0]["captions"][0]["text"])
        self.assertFalse(self.request("state", known)["result"]["projectUnchanged"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.paths = [self.source / "第一条字幕.png", self.source / "20260912_123000.png", self.source / "第三条字幕.png"]
        for path in self.paths:
            Image.new("RGB", (640, 360), "white").save(path)
        self.controller = WebController(self.root / "data")
        self.controller.import_paths(self.paths)

    def tearDown(self):
        self.temp.cleanup()

    def request(self, action, payload=None, **extra):
        project = self.controller.project
        request = {"action": action, "payload": payload or {}, "projectId": project.id, "expectedRevision": project.revision, "requestId": uuid4().hex, **extra}
        return self.controller.dispatch(request)

    def scope(self, index=0):
        asset = self.controller.project.assets[index]
        return {"assetId": asset.id, "captionId": asset.subtitles[0].id}

    def test_filename_text_is_saved_but_not_confirmed(self):
        self.assertEqual(self.controller.project.assets[0].caption_status, CaptionStatus.NEEDS_REVIEW)

    def test_timestamp_name_stays_empty(self):
        self.assertEqual(self.controller.project.assets[1].subtitles, [])
        self.assertEqual(self.controller.project.assets[1].caption_status, CaptionStatus.MISSING)

    def test_unknown_command_does_not_mutate(self):
        revision = self.controller.project.revision
        result = self.request("execute_python", {"code": "print(1)"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.controller.project.revision, revision)

    def test_foreign_project_is_rejected(self):
        self.assertFalse(self.request("rename", {"name": "Bad"}, projectId="other")["ok"])

    def test_stale_revision_is_rejected(self):
        result = self.request("caption_text", {**self.scope(), "text": "更新"}, expectedRevision=-1)
        self.assertEqual(result["error"]["code"], "REVISION_CONFLICT")

    def test_invalid_caption_id_is_rejected(self):
        self.assertFalse(self.request("caption_text", {**self.scope(), "captionId": "missing", "text": "更新"})["ok"])

    def test_request_id_is_idempotent(self):
        project = self.controller.project
        request = {"action": "caption_text", "payload": {**self.scope(), "text": "更新"}, "projectId": project.id, "expectedRevision": project.revision, "requestId": "same"}
        first = self.controller.dispatch(request)
        second = self.controller.dispatch(request)
        self.assertEqual(first, second)
        request["payload"]["text"] = "另一条"
        self.assertEqual(self.controller.dispatch(request)["error"]["code"], "REQUEST_REUSED")

    def test_edit_is_saved_before_acknowledgement(self):
        self.assertTrue(self.request("caption_text", {**self.scope(), "text": "已持久化"})["ok"])
        persisted = self.controller.store.load(self.controller.project_path)
        self.assertEqual(persisted.assets[0].subtitles[0].text, "已持久化")
        self.assertEqual(persisted.revision, self.controller.project.revision)

    def test_failed_save_rolls_back_domain_state(self):
        old = copy.deepcopy(self.controller.project)
        with patch.object(self.controller.store, "save", side_effect=PermissionError("denied")):
            result = self.request("caption_text", {**self.scope(), "text": "不能保存"})
        self.assertEqual(result["error"]["code"], "SAVE_FAILED")
        self.assertEqual(old, self.controller.project)

    def test_confirm_checks_all_captions(self):
        self.request("caption_add", {"assetId": self.scope()["assetId"]})
        result = self.request("confirm", {"assetId": self.scope()["assetId"]})
        self.assertEqual(result["error"]["code"], "CAPTION_EMPTY")
        self.assertEqual(len(result["error"]["affectedIds"]), 1)

    def test_text_changes_invalidate_confirmation_and_undo_restores_it(self):
        self.request("confirm", {"assetId": self.scope()["assetId"]})
        self.request("caption_text", {**self.scope(), "text": "修改后"})
        self.assertEqual(self.controller.project.assets[0].caption_status, CaptionStatus.NEEDS_REVIEW)
        self.request("undo")
        self.assertEqual(self.controller.project.assets[0].caption_status, CaptionStatus.READY)
        self.request("redo")
        self.assertEqual(self.controller.project.assets[0].subtitles[0].text, "修改后")

    def test_style_changes_preserve_text_confirmation(self):
        self.request("confirm", {"assetId": self.scope()["assetId"]})
        self.request("caption_style", {**self.scope(), "style": {"font_size": 100}})
        self.assertEqual(self.controller.project.assets[0].caption_status, CaptionStatus.READY)

    def test_delete_last_caption_does_not_reextract_filename(self):
        self.request("caption_delete", self.scope())
        self.assertEqual(self.controller.project.assets[0].subtitles, [])
        self.assertEqual(self.controller.project.assets[0].caption_status, CaptionStatus.MISSING)

    def test_zero_batch_scope_never_means_all(self):
        old = copy.deepcopy(self.controller.project)
        self.assertFalse(self.request("batch", {"assetIds": [], "operation": "clear"})["ok"])
        self.assertEqual(old, self.controller.project)

    def test_batch_preview_never_mutates_and_skips_source_and_missing(self):
        old = copy.deepcopy(self.controller.project)
        payload = {**self.scope(), "assetIds": [a.id for a in old.assets], "ordinal": 0, "style": True, "position": False, "allCaptions": False}
        preview = self.request("batch_style_preview", payload)
        self.assertTrue(preview["ok"])
        self.assertEqual(len(preview["result"]["updated"]), 1)
        self.assertEqual(len(preview["result"]["skipped"]), 2)
        self.assertEqual(old, self.controller.project)

    def test_batch_style_never_copies_text_or_creates_captions(self):
        self.request("caption_style", {**self.scope(), "style": {"font_size": 72}})
        old = copy.deepcopy(self.controller.project)
        r = self.request("batch_style", {**self.scope(), "assetIds": [a.id for a in old.assets]})
        self.assertTrue(r["ok"])
        self.assertEqual(self.controller.project.assets[2].subtitles[0].text, old.assets[2].subtitles[0].text)
        self.assertEqual(self.controller.project.assets[2].subtitles[0].style_overrides["font_size"], 72)
        self.assertFalse(self.controller.project.assets[1].subtitles)
        self.request("undo")
        self.assertEqual(self.controller.project.assets, old.assets)

    def test_replace_is_explicit_literal_and_transactional(self):
        ids = [a.id for a in self.controller.project.assets]
        result = self.request("replace_preview", {"assetIds": ids, "search": "字幕", "replacement": "对白"})
        self.assertEqual(result["result"]["images"], 2)
        self.request("replace", {"assetIds": ids, "search": "字幕", "replacement": "对白"})
        self.assertEqual(self.controller.project.assets[0].subtitles[0].text, "第一条对白")
        self.request("undo")
        self.assertEqual(self.controller.project.assets[0].subtitles[0].text, "第一条字幕")

    def test_arbitrary_font_path_is_not_a_bridge_parameter(self):
        self.assertFalse(self.request("caption_style", {**self.scope(), "style": {"font_path": "/etc/passwd"}})["ok"])

    def test_nonfinite_and_out_of_range_values_rejected(self):
        for bad in (math.nan, math.inf, -1, 2, True, "0.5"):
            with self.subTest(bad=bad):
                self.assertFalse(self.request("caption_position", {**self.scope(), "x": bad, "y": .5})["ok"])

    def test_preview_requires_matching_revision(self):
        scope = self.scope()
        result = self.request("preview", {"projectId": self.controller.project.id, "revision": -1, "assetId": scope["assetId"], "size": 500})
        self.assertEqual(result["error"]["code"], "REVISION_CONFLICT")

    def test_preview_returns_token_not_arbitrary_path(self):
        result = self.request("preview", {"projectId": self.controller.project.id, "revision": self.controller.project.revision, "assetId": self.scope()["assetId"], "size": 500})
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["width"], 640)
        self.assertIn(result["result"]["token"], self.controller.media)
        self.assertNotIn("source_path", result["result"])

    def test_preflight_blocks_unconfirmed_captions(self):
        self.controller.outputs["output"] = self.root / "output"
        result = self.request("preflight", {"outputToken": "output"})
        self.assertTrue(result["result"]["errors"])

    def test_preflight_rejects_ungranted_output_path(self):
        result = self.request("preflight", {"outputToken": str(self.root)})
        self.assertEqual(result["error"]["code"], "OUTPUT_REQUIRED")

    def test_export_cannot_start_with_stale_preflight(self):
        self.controller.outputs["output"] = self.root / "output"
        result = self.request("preflight", {"outputToken": "output"})
        self.request("rename", {"name": "改变版本"})
        self.assertEqual(self.request("start_export", {"preflightId": result["result"]["id"]})["error"]["code"], "PREFLIGHT_EXPIRED")

    def test_export_lock_blocks_mutation(self):
        self.controller.job = {"id": "job", "state": "running", "items": [], "revision": 1, "output_dir": self.root, "error": None}
        self.assertEqual(self.request("rename", {"name": "禁止"})["error"]["code"], "EXPORT_BUSY")

    def test_untrusted_project_does_not_grant_external_paths(self):
        self.controller.grants.clear()
        self.controller.open_project(self.controller.project_path)
        self.assertFalse(self.controller.grants)
        self.assertEqual(self.controller.project.assets[0].caption_status, CaptionStatus.UNREADABLE)


class WebSafetyTests(unittest.TestCase):
    def test_windows_reserved_and_traversal_names_rejected(self):
        for value in ("CON.png", "aux", "LPT9.jpg", "a/b.jpg", "a\\b.jpg", "a?.png", "name.", "name ", "nul.txt"):
            self.assertFalse(windows_filename(value), value)
        self.assertTrue(windows_filename("我的字幕.png"))

    def test_unknown_style_keys_rejected(self):
        with self.assertRaises(CommandError):
            style_patch({"evil": True})

    def test_atomic_output_never_clobbers_racing_writer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.png"; output = root / "output.png"
            Image.new("RGB", (50, 50), "white").save(source)
            import os
            publish = "rename" if os.name == "nt" else "link"
            original = getattr(os, publish)
            def race(src, dst):
                Path(dst).write_bytes(b"other writer")
                original(src, dst)
            with patch(f"subtitle_app.export_service.os.{publish}", side_effect=race):
                with self.assertRaises(FileExistsError):
                    ExportService().export_image(source, output, [], StyleSettings())
            self.assertEqual(output.read_bytes(), b"other writer")
            self.assertFalse(list(root.glob(".*.tmp*")))

    def test_jpeg_transparency_has_white_background(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "transparent.png"; output = root / "white.jpg"
            Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(source)
            ExportService().export_image(source, output, [], StyleSettings())
            with Image.open(output) as result:
                self.assertGreater(min(result.getpixel((0, 0))), 250)


if __name__ == "__main__":
    unittest.main()
