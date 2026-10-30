"""Unified style with per-caption exceptions (spec 4.1): the rules, without the controller."""
import unittest
from datetime import datetime
from pathlib import Path

from subtitle_app import style_model as sm
from subtitle_app.filename_classifier import FilenameKind
from subtitle_app.models import Asset, CaptionStatus, Project, SubtitleItem, SubtitleSource


def caption(identifier, **overrides):
    item = SubtitleItem(identifier, "字幕", SubtitleSource.MANUAL)
    item.style_overrides.update(overrides)
    return item


def project(*images, **default):
    """`images` are lists of captions; each list becomes one image."""
    now = datetime.now().astimezone()
    result = Project.create("测试")
    result.default_style = dict(default)
    result.assets = [Asset(f"a{n}", Path(f"/tmp/{n}.png"), f"{n}.png", now, now, n, FilenameKind.CAPTION, CaptionStatus.READY, list(captions))
                     for n, captions in enumerate(images)]
    return result


class WriteTests(unittest.TestCase):
    def test_write_unified_moves_value_and_clears_current(self):
        a, b = caption("a", font_size=70), caption("b", font_size=80)
        p = project([a], [b], font_size=54)
        sm.write_unified(p, a, {"font_size": 60})
        self.assertEqual(60, p.default_style["font_size"])
        self.assertNotIn("font_size", a.style_overrides)
        self.assertEqual(80, b.style_overrides["font_size"])

    def test_write_unified_drops_overrides_equal_to_new_value(self):
        a, b = caption("a"), caption("b", font_size=60)
        p = project([a, b], font_size=54)
        sm.write_unified(p, a, {"font_size": 60})
        self.assertNotIn("font_size", b.style_overrides)

    def test_font_identity_moves_as_one(self):
        a = caption("a", font_path="/x", font_family="X", font_index=0, font_weight=900)
        p = project([a])
        sm.write_unified(p, a, {"font_path": "/y", "font_family": "Y", "font_index": 0, "font_weight": None})
        self.assertFalse(set(sm.FONT_KEYS) & set(a.style_overrides))
        self.assertEqual("Y", p.default_style["font_family"])

    def test_font_identity_moves_as_one_even_for_one_key(self):
        a = caption("a", font_path="/x", font_family="X", font_index=0, font_weight=900)
        p = project([a])
        sm.write_unified(p, a, {"font_weight": 700})
        self.assertFalse(set(sm.FONT_KEYS) & set(a.style_overrides))

    def test_position_keys_stay_on_caption(self):
        a = caption("a")
        p = project([a], font_size=54)
        sm.write_unified(p, a, {"max_width": .5, "font_size": 60})
        self.assertNotIn("max_width", p.default_style)
        self.assertEqual(.5, a.style_overrides["max_width"])
        self.assertEqual(60, p.default_style["font_size"])

    def test_override_equal_to_unified_is_not_kept(self):
        a, b = caption("a"), caption("b")
        p = project([a, b])
        sm.write_override(p, a, {"text_color": (255, 255, 255, 255)})
        sm.write_override(p, b, {"text_color": [255, 255, 255, 255]})
        self.assertNotIn("text_color", a.style_overrides)
        self.assertNotIn("text_color", b.style_overrides)

    def test_override_different_from_unified_is_kept(self):
        a = caption("a")
        p = project([a])
        sm.write_override(p, a, {"text_color": (255, 220, 65, 255), "max_width": .6})
        self.assertEqual((255, 220, 65, 255), a.style_overrides["text_color"])
        self.assertEqual(.6, a.style_overrides["max_width"])


class RestoreTests(unittest.TestCase):
    def test_restore_counts_changed_captions(self):
        a, b, c = caption("a", font_size=70), caption("b", font_size=80), caption("c")
        project([a, b, c], font_size=54)
        self.assertEqual(2, sm.restore([a, b, c], ["font_size"]))
        self.assertNotIn("font_size", a.style_overrides)

    def test_restore_defaults_to_every_appearance_field_and_keeps_position(self):
        a = caption("a", font_size=70, text_color=(1, 2, 3, 255), max_width=.5)
        self.assertEqual(1, sm.restore([a]))
        self.assertEqual({"max_width": .5}, a.style_overrides)

    def test_overridden_lists_appearance_keys_in_order(self):
        a = caption("a", stroke_width=3, font_size=70, max_width=.5)
        self.assertEqual(["font_size", "stroke_width"], sm.overridden(a))

    def test_groups_keep_font_identity_whole(self):
        self.assertEqual([sm.FONT_KEYS, ("font_size",)], sm.groups(["font_size", "font_weight", "max_width"]))



def effective(p, item):
    return {**sm.unified(p), **item.style_overrides}


class FoldTests(unittest.TestCase):
    """Projects from before the unified style: one fold, and nothing on screen changes (spec 4.1 旧项目)."""

    def test_fold_picks_majority_and_keeps_minorities(self):
        own = [caption(f"o{n}", font_size=80) for n in range(6)]
        followers = [caption(f"f{n}") for n in range(4)]
        p = project(own[:3], own[3:] + followers[:2], followers[2:])
        before = {c.id: effective(p, c)["font_size"] for c in own + followers}
        sm.fold_majority(p)
        self.assertEqual(80, p.default_style["font_size"])
        for item in followers:
            self.assertEqual(110, item.style_overrides["font_size"])
        for item in own:
            self.assertNotIn("font_size", item.style_overrides)
        self.assertEqual(before, {c.id: effective(p, c)["font_size"] for c in own + followers})

    def test_fold_keeps_followers_of_old_default(self):
        yellow = (255, 220, 65, 255)
        own = [caption(f"o{n}", text_color=list(yellow)) for n in range(6)]
        followers = [caption(f"f{n}") for n in range(4)]
        p = project(own, followers)
        before = {c.id: list(effective(p, c)["text_color"]) for c in own + followers}
        sm.fold_majority(p)
        self.assertEqual(list(yellow), list(p.default_style["text_color"]))
        self.assertEqual(before, {c.id: list(effective(p, c)["text_color"]) for c in own + followers})
        self.assertTrue(all("text_color" in c.style_overrides for c in followers))

    def test_fold_treats_font_identity_as_one(self):
        font_a = {"font_path": "/a.ttf", "font_family": "A", "font_index": 0, "font_weight": 900}
        own = [caption(f"o{n}", **font_a) for n in range(6)]
        followers = [caption(f"f{n}") for n in range(4)]
        p = project(own, followers, font_path="/b.ttf", font_family="B", font_index=0, font_weight=None)
        sm.fold_majority(p)
        self.assertEqual("A", p.default_style["font_family"])
        for item in followers:
            self.assertEqual({"font_path": "/b.ttf", "font_family": "B", "font_index": 0, "font_weight": None},
                             {key: item.style_overrides[key] for key in sm.FONT_KEYS})
        self.assertTrue(all(not set(sm.FONT_KEYS) & set(c.style_overrides) for c in own))

    def test_fold_tie_prefers_current_unified(self):
        p = project([caption("a", font_size=80), caption("b", font_size=80), caption("c"), caption("d")])
        sm.fold_majority(p)
        self.assertNotIn("font_size", p.default_style)
        self.assertEqual(2, sum("font_size" in c.style_overrides for c in sm.captions(p)))

    def test_fold_marks_project(self):
        p = project([caption("a", font_size=80)])
        sm.fold_majority(p)
        self.assertEqual(2, p.style_model)
        empty = project()
        sm.fold_majority(empty)
        self.assertEqual(2, empty.style_model)



class ScaleTests(unittest.TestCase):
    def test_write_override_never_stores_a_reference_edge(self):
        a = caption("a")
        p = project([a], reference_edge=1080)
        sm.write_override(p, a, {"reference_edge": None, "font_size": 70})
        self.assertEqual({"font_size": 70}, a.style_overrides)

    def test_rescale_touches_only_pixel_sizes(self):
        self.assertEqual({"font_size": 36.0, "stroke_width": 1.33, "text_color": (1, 2, 3, 255)},
                         sm.rescale({"font_size": 54, "stroke_width": 2, "text_color": (1, 2, 3, 255)}, 720 / 1080))

    def test_short_edge(self):
        a = project([caption("a")])
        asset = a.assets[0]
        self.assertIsNone(sm.short_edge(asset))
        asset.width, asset.height = 1920, 1080
        self.assertEqual(1080, sm.short_edge(asset))



class ProportionalTests(unittest.TestCase):
    """Spec 4.2: 「改为按画面比例」 for projects with fixed pixels."""

    def sized(self, p, *sizes):
        for asset, size in zip(p.assets, sizes):
            asset.width, asset.height = size
        return p

    def test_most_common_short_edge_becomes_the_reference(self):
        p = self.sized(project([caption("a")], [caption("b")], [caption("c")], [caption("d")], font_size=110),
                       (1920, 1080), (1280, 720), (1080, 1920), (1920, 1080))
        self.assertEqual(1080, sm.to_proportional(p))
        self.assertEqual((1080, 110), (p.default_style["reference_edge"], p.default_style["font_size"]))

    def test_overrides_keep_their_own_picture_look(self):
        big, small = caption("big", font_size=70), caption("small", font_size=80, stroke_width=3)
        p = self.sized(project([big], [small], [caption("c")], font_size=110), (1920, 1080), (1280, 720), (1920, 1080))
        sm.to_proportional(p)
        self.assertEqual(70, big.style_overrides["font_size"])
        self.assertEqual({"font_size": 120.0, "stroke_width": 4.5}, small.style_overrides)

    def test_unknown_size_keeps_override_values(self):
        unknown = caption("u", font_size=80)
        p = self.sized(project([unknown], [caption("b")], font_size=110), (None, None), (1920, 1080))
        sm.to_proportional(p)
        self.assertEqual(80, unknown.style_overrides["font_size"])

    def test_no_known_sizes_uses_1080(self):
        self.assertEqual(1080, sm.to_proportional(project([caption("a")])))


if __name__ == "__main__":
    unittest.main()
