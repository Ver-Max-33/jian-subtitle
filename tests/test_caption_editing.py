"""Caption editing redesign (2026-10-30 spec): unified style, scopes, restore, sizes, batch confirm, speaker prefix."""
import unittest

from test_backend_r4 import ControllerCase


def rgba(value):
    return list(value)


class ScopeCase(ControllerCase):
    """Image 1 has two captions, image 2 one; image 2's caption has its own font size (80)."""

    def setUp(self):
        super().setUp()
        self.c.import_paths([self.image("【你平时常来这里吗？】【几乎每个周末都来。】.png", size=(1280, 720)),
                             self.image("车站这边总是很多人.png", size=(1280, 720))])
        by_name = {a.filename: a for a in self.c.project.assets}
        one, two = by_name["【你平时常来这里吗？】【几乎每个周末都来。】.png"], by_name["车站这边总是很多人.png"]
        self.img1, self.img2 = one.id, two.id
        self.c1, self.c2 = (c.id for c in one.subtitles)
        self.c3 = two.subtitles[0].id
        self.style(self.img2, self.c3, {"font_size": 80})

    def style(self, asset_id, caption_id, style, scope="caption"):
        return self.ok("caption_style", {"assetId": asset_id, "captionId": caption_id, "style": style, "scope": scope})

    def view(self, caption_id):
        for asset in self.c.snapshot()["project"]["assets"]:
            for caption in asset["captions"]:
                if caption["id"] == caption_id:
                    return caption
        raise KeyError(caption_id)

    def unified(self):
        return self.c.snapshot()["project"]["style"]

    def raw(self, caption_id):
        return next(c for a in self.c.project.assets for c in a.subtitles if c.id == caption_id).style_overrides


class ScopeTests(ScopeCase):
    def test_all_scope_changes_every_follower(self):
        self.style(self.img1, self.c1, {"font_size": 60}, "all")
        self.assertEqual(60, self.view(self.c1)["style"]["font_size"])
        self.assertEqual(60, self.view(self.c2)["style"]["font_size"])
        self.assertEqual(80, self.view(self.c3)["style"]["font_size"])

    def test_all_scope_clears_current_override(self):
        self.style(self.img1, self.c1, {"font_size": 70})
        self.style(self.img1, self.c1, {"font_size": 60}, "all")
        self.assertNotIn("font_size", self.view(self.c1)["overrides"])
        self.assertEqual(60, self.view(self.c1)["style"]["font_size"])

    def test_caption_scope_writes_only_override(self):
        before = rgba(self.unified()["text_color"])
        self.style(self.img1, self.c1, {"text_color": [10, 20, 30, 255]})
        self.assertEqual(["text_color"], self.view(self.c1)["overrides"])
        self.assertEqual([], self.view(self.c2)["overrides"])
        self.assertEqual(before, rgba(self.unified()["text_color"]))

    def test_undo_unified_write_restores_override(self):
        before = self.unified()["font_size"]
        self.style(self.img1, self.c1, {"font_size": 70})
        self.style(self.img1, self.c1, {"font_size": 60}, "all")
        self.ok("undo")
        self.assertEqual(before, self.unified()["font_size"])
        self.assertIn("font_size", self.view(self.c1)["overrides"])
        self.assertEqual(70, self.view(self.c1)["style"]["font_size"])

    def test_apply_preset_all_replaces_unified(self):
        self.ok("apply_preset", {"assetId": self.img1, "captionId": self.c1, "name": "强调", "scope": "all"})
        self.assertEqual([255, 220, 65, 255], rgba(self.unified()["text_color"]))
        self.assertEqual([255, 220, 65, 255], rgba(self.view(self.c2)["style"]["text_color"]))
        self.assertEqual([255, 220, 65, 255], rgba(self.view(self.c3)["style"]["text_color"]))

    def test_apply_preset_caption_scope_stays_on_caption(self):
        before = rgba(self.unified()["text_color"])
        self.ok("apply_preset", {"assetId": self.img1, "captionId": self.c1, "name": "强调", "scope": "caption"})
        self.assertEqual([255, 220, 65, 255], rgba(self.view(self.c1)["style"]["text_color"]))
        self.assertEqual(before, rgba(self.view(self.c2)["style"]["text_color"]))

    def test_scope_is_validated(self):
        reply = self.call("caption_style", {"assetId": self.img1, "captionId": self.c1, "style": {"font_size": 60}, "scope": "everything"})
        self.assertFalse(reply["ok"])

    def test_snapshot_lists_overrides_and_unified_style(self):
        self.assertEqual(["font_size"], self.view(self.c3)["overrides"])
        self.assertEqual([], self.view(self.c1)["overrides"])
        unified = self.unified()
        self.assertIn("font_id", unified)
        self.assertNotIn("font_path", unified)


class RestoreTests(ScopeCase):
    def test_style_restore_field_everywhere_one_undo(self):
        self.style(self.img1, self.c1, {"font_size": 70})
        self.style(self.img1, self.c2, {"font_size": 75})
        self.assertEqual({"restored": 3}, self.ok("style_restore", {"scope": "field", "keys": ["font_size"]}))
        self.assertEqual([], self.view(self.c3)["overrides"])
        self.ok("undo")
        self.assertEqual(70, self.view(self.c1)["style"]["font_size"])
        self.assertEqual(75, self.view(self.c2)["style"]["font_size"])
        self.assertEqual(80, self.view(self.c3)["style"]["font_size"])

    def test_style_restore_selection_scope(self):
        self.style(self.img1, self.c1, {"font_size": 70})
        self.style(self.img1, self.c2, {"font_size": 75})
        self.assertEqual({"restored": 2}, self.ok("style_restore", {"scope": "selection", "assetIds": [self.img1, self.img2], "captions": 0}))
        self.assertEqual([], self.view(self.c1)["overrides"])
        self.assertEqual(["font_size"], self.view(self.c2)["overrides"])
        self.assertEqual([], self.view(self.c3)["overrides"])

    def test_style_restore_caption_and_project(self):
        self.style(self.img1, self.c1, {"font_size": 70, "text_color": [10, 20, 30, 255]})
        self.ok("style_restore", {"scope": "caption", "assetId": self.img1, "captionId": self.c1, "keys": ["text_color"]})
        self.assertEqual(["font_size"], self.view(self.c1)["overrides"])
        self.assertEqual({"restored": 2}, self.ok("style_restore", {"scope": "project"}))
        self.assertEqual([], self.view(self.c1)["overrides"])

    def test_style_restore_rejects_position_keys(self):
        reply = self.call("style_restore", {"scope": "field", "keys": ["max_width"]})
        self.assertFalse(reply["ok"])
        self.assertEqual("INVALID_INPUT", reply["error"]["code"])

    def test_reset_style_keeps_position_fields(self):
        self.style(self.img1, self.c1, {"max_width": .5, "font_size": 70})
        self.ok("caption_reset", {"assetId": self.img1, "captionId": self.c1, "scope": "style"})
        self.assertEqual({"max_width": .5}, self.raw(self.c1))

    def test_batch_set_does_not_store_values_equal_to_unified(self):
        size = self.unified()["font_size"]
        self.ok("batch_set", {"assetIds": [self.img1, self.img2], "captions": "all", "style": {"font_size": size}})
        self.assertEqual([], self.view(self.c3)["overrides"])
        self.assertEqual([], self.view(self.c1)["overrides"])



class OldProjectTests(ScopeCase):
    def test_open_old_project_keeps_look(self):
        yellow = [255, 220, 65, 255]
        self.style(self.img1, self.c1, {"text_color": yellow})
        self.style(self.img1, self.c2, {"text_color": yellow})
        self.c.project.style_model = 1
        self.c.store.save(self.c.project, self.c.project_path)
        looks = lambda: {c: {k: list(v) if isinstance(v, tuple) else v for k, v in self.view(c)["style"].items()} for c in (self.c1, self.c2, self.c3)}  # noqa: E731
        before = looks()
        revision = self.c.project.revision
        self.c.open_project(self.c.project_path)
        self.assertEqual(before, looks())
        self.assertEqual(yellow, rgba(self.unified()["text_color"]))
        self.assertEqual(["font_size", "text_color"], self.view(self.c3)["overrides"])
        self.assertEqual(2, self.c.project.style_model)
        self.assertFalse(self.c.snapshot()["canUndo"])
        self.assertEqual(revision, self.c.project.revision)

    def test_new_project_is_marked(self):
        self.assertEqual(2, self.c.project.style_model)



class SizeTests(ScopeCase):
    def test_style_patch_accepts_fractions(self):
        from subtitle_app.web_contracts import CommandError, style_patch
        self.assertEqual(54.08, style_patch({"font_size": 54.08})["font_size"])
        self.assertEqual(1.33, style_patch({"stroke_width": 1.333})["stroke_width"])
        with self.assertRaises(CommandError):
            style_patch({"reference_edge": 1080})

    def test_stored_reference_edge_is_validated(self):
        from subtitle_app.web_contracts import CommandError, validate_style_values
        self.assertEqual(1080, validate_style_values({"font_size": 54, "reference_edge": 1080}).reference_edge)
        with self.assertRaises(CommandError):
            validate_style_values({"reference_edge": 3})

    def test_snapshot_reference_edge(self):
        self.c.project.default_style.pop("reference_edge", None)
        self.c._snapshot_project = None
        self.assertIsNone(self.c.snapshot()["project"]["referenceEdge"])
        self.c.project.default_style["reference_edge"] = 1080
        self.c._snapshot_project = None
        self.assertEqual(1080, self.c.snapshot()["project"]["referenceEdge"])



class PresetSizeTests(ControllerCase):
    """Spec 4.2: new projects at 5 % of the short edge; presets remember the picture they were saved on."""

    def setUp(self):
        super().setUp()
        self.c.import_paths([self.image("大图字幕.png", size=(1920, 1080)), self.image("小图字幕.png", size=(1280, 720))])
        by_name = {a.filename: a for a in self.c.project.assets}
        self.big, self.small = by_name["大图字幕.png"], by_name["小图字幕.png"]

    def caption_style(self, asset):
        caption = asset.subtitles[0].id
        for view in self.c.snapshot()["project"]["assets"]:
            if view["id"] == asset.id:
                return view["captions"][0]

    def test_new_project_uses_five_percent(self):
        self.assertEqual(54, self.c.project.default_style["font_size"])
        self.assertEqual(1080, self.c.project.default_style["reference_edge"])

    def test_new_project_with_user_default_keeps_its_size(self):
        from subtitle_app.models import StyleSettings
        self.c.presets.save("我的", StyleSettings(font_size=72, reference_edge=720))
        self.c.presets.set_default("我的")
        self.ok("new_project", {"name": "另一个"})
        self.assertEqual(72, self.c.project.default_style["font_size"])
        self.assertEqual(720, self.c.project.default_style["reference_edge"])

    def test_saved_preset_records_short_edge(self):
        self.ok("preset", {"operation": "save", "name": "小图", "assetId": self.small.id, "captionId": self.small.subtitles[0].id})
        saved = self.c.presets.list()["小图"]
        self.assertEqual((36, 720), (saved.font_size, saved.reference_edge))

    def test_preset_from_720_applies_proportionally(self):
        self.ok("preset", {"operation": "save", "name": "小图", "assetId": self.small.id, "captionId": self.small.subtitles[0].id})
        self.ok("apply_preset", {"assetId": self.big.id, "captionId": self.big.subtitles[0].id, "name": "小图", "scope": "caption"})
        view = self.caption_style(self.big)
        self.assertEqual(54, view["style"]["font_size"])
        self.assertNotIn("font_size", view["overrides"])
        self.assertEqual(1080, view["style"]["reference_edge"])

    def test_old_preset_treated_as_1080(self):
        from subtitle_app.models import StyleSettings
        self.c.presets.save("旧", StyleSettings(font_size=108))
        self.ok("apply_preset", {"assetId": self.big.id, "captionId": self.big.subtitles[0].id, "name": "旧", "scope": "caption"})
        self.assertEqual(108, self.caption_style(self.big)["style"]["font_size"])

    def test_builtin_never_turns_a_caption_into_fixed_pixels(self):
        self.ok("apply_preset", {"assetId": self.big.id, "captionId": self.big.subtitles[0].id, "name": "强调", "scope": "caption"})
        self.assertEqual(1080, self.caption_style(self.big)["style"]["reference_edge"])
        self.ok("batch_set", {"assetIds": [self.big.id, self.small.id], "captions": 0, "preset": "柔和"})
        self.assertEqual(1080, self.caption_style(self.small)["style"]["reference_edge"])
        self.assertTrue(all("reference_edge" not in c.style_overrides for a in self.c.project.assets for c in a.subtitles))

    def test_builtin_in_pixel_project_scales_stroke(self):
        self.c.project.default_style.pop("reference_edge")
        self.ok("apply_preset", {"assetId": self.small.id, "captionId": self.small.subtitles[0].id, "name": "经典", "scope": "caption"})
        style = self.caption_style(self.small)["style"]
        self.assertEqual(1.33, style["stroke_width"])
        self.assertEqual(6.67, style["line_spacing"])



class ToProportionalTests(ControllerCase):
    def setUp(self):
        super().setUp()
        names = ("第一张字幕", "第二张字幕", "第三张字幕")
        self.c.import_paths([self.image(f"{n}.png", size=(1920, 1080)) for n in names] + [self.image("小图字幕.png", size=(1280, 720))])
        self.c.project.default_style.pop("reference_edge")
        self.c.project.default_style["font_size"] = 110
        self.small = next(a for a in self.c.project.assets if a.filename == "小图字幕.png")
        self.big = next(a for a in self.c.project.assets if a.filename == "第一张字幕.png")

    def height(self, asset):
        from subtitle_app.models import CaptionRenderRequest, StyleSettings
        from subtitle_app.render_service import RenderService
        caption = next(a for a in self.c.project.assets if a.id == asset.id).subtitles[0]
        style = StyleSettings.from_mapping(self.c._style(caption))
        return RenderService().measure((asset.width, asset.height), [CaptionRenderRequest("测试字幕", (.5, .5), 0, style)], style)[0]["height"] * asset.height

    def test_common_size_unchanged_others_scale(self):
        big, small = self.height(self.big), self.height(self.small)
        self.assertEqual({"referenceEdge": 1080}, self.ok("style_to_proportional"))
        self.assertAlmostEqual(big, self.height(self.big), delta=1)
        self.assertAlmostEqual(small * 2 / 3, self.height(self.small), delta=2)

    def test_override_keeps_its_own_image_look(self):
        self.ok("caption_style", {"assetId": self.small.id, "captionId": self.small.subtitles[0].id, "style": {"font_size": 80}})
        before = self.height(self.small)
        self.ok("style_to_proportional")
        self.assertEqual(120, self.c.project.assets[[a.id for a in self.c.project.assets].index(self.small.id)].subtitles[0].style_overrides["font_size"])
        self.assertAlmostEqual(before, self.height(self.small), delta=1)

    def test_to_proportional_one_undo(self):
        self.ok("style_to_proportional")
        self.ok("undo")
        self.assertNotIn("reference_edge", self.c.project.default_style)
        reply = self.call("style_to_proportional")
        self.assertTrue(reply["ok"])
        reply = self.call("style_to_proportional")
        self.assertEqual("ALREADY_PROPORTIONAL", reply["error"]["code"])



class ConfirmBatchTests(ControllerCase):
    """Spec 4.5: confirm the selected images whose captions are all filled in; report the rest."""

    def setUp(self):
        super().setUp()
        self.c.import_paths([self.image(f"{name}.png", size=(640, 360)) for name in ("字幕齐全", "空字幕", "IMG_0836", "无需字幕")])
        self.by_name = {a.filename: a.id for a in self.c.project.assets}
        empty = next(a for a in self.c.project.assets if a.filename == "空字幕.png")
        self.ok("caption_text", {"assetId": empty.id, "captionId": empty.subtitles[0].id, "text": ""})
        self.ok("batch", {"operation": "no_caption", "assetIds": [self.by_name["无需字幕.png"]]})

    def status(self, name):
        return next(a for a in self.c.project.assets if a.filename == name).caption_status.value

    def test_confirm_batch_confirms_ready_and_reports_skips(self):
        result = self.ok("confirm_batch", {"assetIds": list(self.by_name.values())})
        self.assertEqual([self.by_name["字幕齐全.png"]], result["confirmed"])
        self.assertEqual({(self.by_name["空字幕.png"], "有空字幕"), (self.by_name["IMG_0836.png"], "没有字幕")},
                         {(item["id"], item["reason"]) for item in result["skipped"]})
        self.assertEqual("ready", self.status("字幕齐全.png"))
        self.assertEqual("no_caption", self.status("无需字幕.png"))

    def test_confirm_batch_one_undo(self):
        before = {name: self.status(name) for name in self.by_name}
        self.ok("confirm_batch", {"assetIds": list(self.by_name.values())})
        self.ok("undo")
        self.assertEqual(before, {name: self.status(name) for name in self.by_name})

    def test_unreadable_source_is_skipped(self):
        path = next(a for a in self.c.project.assets if a.filename == "字幕齐全.png").source_path
        path.unlink()
        result = self.ok("confirm_batch", {"assetIds": [self.by_name["字幕齐全.png"]]})
        self.assertEqual([], result["confirmed"])
        self.assertEqual("图片不可读", result["skipped"][0]["reason"])



class SpeakerPrefixTests(ScopeCase):
    def test_project_settings_one_undo(self):
        self.assertTrue(self.c.snapshot()["project"]["showSpeaker"])
        self.ok("project_settings", {"showSpeaker": False})
        self.assertFalse(self.c.snapshot()["project"]["showSpeaker"])
        self.ok("undo")
        self.assertTrue(self.c.snapshot()["project"]["showSpeaker"])
        self.assertFalse(self.call("project_settings", {"showSpeaker": "no"})["ok"])

    def test_preview_follows_switch(self):
        self.ok("caption_speaker", {"assetId": self.img2, "captionId": self.c3, "speaker": "主持人"})

        def width():
            p = self.c.project
            preview = self.c.preview({"assetId": self.img2, "projectId": p.id, "revision": p.revision, "editable": True, "layersOnly": True})
            return preview["overlays"][0]["renderWidth"]

        shown = width()
        self.ok("project_settings", {"showSpeaker": False})
        self.assertLess(width(), shown)


if __name__ == "__main__":
    unittest.main()
