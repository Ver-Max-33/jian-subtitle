import tempfile
import unittest
from pathlib import Path

from PIL import Image

from subtitle_app.export_planner import ExportPlanner
from subtitle_app.import_service import ImportService
from subtitle_app.models import CaptionStatus, ExportOptions, NamingMode, Project


class ExportPlannerTests(unittest.TestCase):
    def test_names_that_differ_only_in_unicode_form_are_numbered(self):
        # macOS treats 「café」 written two ways as one name: the second file used to fail instead of being numbered.
        import unicodedata
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for folder, form in (("a", "NFC"), ("b", "NFD")):
                (root / folder).mkdir()
                paths.append(root / folder / unicodedata.normalize(form, "café.png"))
                Image.new("RGB", (100, 80), "white").save(paths[-1])
            project = Project.create("同名", ImportService().import_paths(paths).assets)
            names = [item.output_path.name for item in ExportPlanner().plan(project, ExportOptions(output_dir=root / "out")).items]
            self.assertEqual(2, len({unicodedata.normalize("NFC", name).casefold() for name in names}), names)

    def test_plan_hides_speaker_when_off(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "我常来这里.png"
            Image.new("RGB", (100, 80), "white").save(source)
            project = Project.create("说话人", ImportService().import_paths([source]).assets)
            project.assets[0].subtitles[0].speaker_id = "小林"
            options = ExportOptions(output_dir=root / "output")
            self.assertEqual("小林：我常来这里", ExportPlanner().plan(project, options).items[0].captions[0].text)
            project.show_speaker = False
            self.assertEqual("我常来这里", ExportPlanner().plan(project, options).items[0].captions[0].text)

    def test_sequence_naming_uses_start_number_and_fixed_digits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "第一张.png"
            second = root / "第二张.png"
            Image.new("RGB", (100, 80), "white").save(first)
            Image.new("RGB", (100, 80), "white").save(second)
            assets = ImportService().import_paths([first, second]).assets
            project = Project.create("导出项目", assets)

            plan = ExportPlanner().plan(
                project,
                ExportOptions(
                    output_dir=root / "output",
                    naming_mode=NamingMode.SEQUENCE,
                    start_number=7,
                    digits=3,
                ),
            )

        self.assertEqual(["007.png", "008.png"], [item.output_path.name for item in plan.items])

    def test_existing_output_name_is_resolved_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "字幕.png"
            output_dir = root / "output"
            output_dir.mkdir()
            Image.new("RGB", (100, 80), "white").save(source)
            (output_dir / "字幕.png").write_bytes(b"existing")
            project = Project.create(
                "冲突项目", ImportService().import_paths([source]).assets
            )

            plan = ExportPlanner().plan(
                project,
                ExportOptions(output_dir=output_dir),
            )

        self.assertEqual("字幕_2.png", plan.items[0].output_path.name)

    def test_subtitle_style_override_is_merged_over_project_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "局部样式.png"
            Image.new("RGB", (100, 80), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]
            asset.subtitles[0].style_overrides = {"font_size": 66, "effect": "shadow"}
            project = Project.create("样式合并", [asset])
            project.default_style = {"font_size": 40, "stroke_width": 2}

            plan = ExportPlanner().plan(
                project,
                ExportOptions(output_dir=root / "output"),
            )

        caption_style = plan.items[0].captions[0].style
        self.assertEqual(66, caption_style.font_size)
        self.assertEqual(2, caption_style.stroke_width)
        self.assertEqual("shadow", caption_style.effect)

    def test_unreadable_asset_is_a_blocking_preflight_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "损坏.png"
            source.write_bytes(b"not an image")
            project = Project.create(
                "损坏项目", ImportService().import_paths([source]).assets
            )

            plan = ExportPlanner().plan(
                project,
                ExportOptions(output_dir=root / "output"),
            )

        self.assertEqual([], plan.items)
        self.assertEqual(1, len(plan.blocking_errors))

    def test_needs_review_asset_remains_exportable_with_one_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "【括号不完整.png"
            Image.new("RGB", (100, 80), "white").save(source)
            project = Project.create(
                "待确认项目", ImportService().import_paths([source]).assets
            )

            plan = ExportPlanner().plan(
                project,
                ExportOptions(output_dir=root / "output"),
            )

        self.assertEqual(1, len(plan.items))
        self.assertTrue(any("需确认" in warning for warning in plan.warnings))

    def test_disabling_source_format_converts_output_to_png(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "字幕.jpg"
            Image.new("RGB", (100, 80), "white").save(source)
            project = Project.create(
                "格式项目", ImportService().import_paths([source]).assets
            )

            plan = ExportPlanner().plan(
                project,
                ExportOptions(output_dir=root / "output", preserve_format=False),
            )

        self.assertEqual("字幕.png", plan.items[0].output_path.name)
        self.assertFalse(plan.items[0].copy_original)

    def test_source_removed_after_import_is_blocking_before_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "稍后删除.png"
            Image.new("RGB", (100, 80), "white").save(source)
            project = Project.create(
                "缺失项目", ImportService().import_paths([source]).assets
            )
            source.unlink()

            plan = ExportPlanner().plan(
                project,
                ExportOptions(output_dir=root / "output"),
            )

        self.assertTrue(any("源文件不存在" in error for error in plan.blocking_errors))

    def test_excluded_no_caption_assets_do_not_consume_sequence_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            no_caption = root / "20260121_021602.png"
            caption = root / "需要输出.png"
            Image.new("RGB", (100, 80), "white").save(no_caption)
            Image.new("RGB", (100, 80), "white").save(caption)
            project = Project.create(
                "连续编号",
                ImportService().import_paths([no_caption, caption]).assets,
            )

            plan = ExportPlanner().plan(
                project,
                ExportOptions(
                    output_dir=root / "output",
                    naming_mode=NamingMode.SEQUENCE,
                    start_number=1,
                    digits=3,
                    include_no_caption=False,
                ),
            )

        self.assertEqual(["001.png"], [item.output_path.name for item in plan.items])

    def test_explicit_no_caption_status_is_not_reported_as_a_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "20260121_021602.png"
            Image.new("RGB", (100, 80), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]
            asset.caption_status = CaptionStatus.NO_CAPTION
            project = Project.create("无需字幕", [asset])

            plan = ExportPlanner().plan(
                project, ExportOptions(output_dir=root / "output")
            )

        self.assertFalse(any("没有字幕" in warning for warning in plan.warnings))
        self.assertTrue(plan.items[0].copy_original)

    def test_empty_captions_are_not_drawn(self):
        # An empty caption with a background would export as an empty dark box.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "第一条.png"
            Image.new("RGB", (100, 80), "white").save(source)
            project = Project.create("空字幕", ImportService().import_paths([source]).assets)
            subtitles = project.assets[0].subtitles
            subtitles.append(type(subtitles[0])("second", "  ", subtitles[0].source))
            subtitles.append(type(subtitles[0])("third", "第三条", subtitles[0].source))
            captions = ExportPlanner().plan(project, ExportOptions(output_dir=root / "output")).items[0].captions
            self.assertEqual(["第一条", "第三条"], [c.text for c in captions])
            # Slots count the empty caption too: 第一条 stays where the canvas shows it, on top of three.
            self.assertEqual((0.5, round(0.86 - 2 * .12, 2)), (captions[0].position_ratio[0], round(captions[0].position_ratio[1], 2)))
            self.assertEqual(0.86, round(captions[1].position_ratio[1], 2))


if __name__ == "__main__":
    unittest.main()
