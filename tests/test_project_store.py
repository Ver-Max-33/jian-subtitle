import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from subtitle_app.import_service import ImportService
from subtitle_app.models import CaptionStatus, Project, SubtitleSource
from subtitle_app.project_store import ProjectStore


class ProjectStoreTests(unittest.TestCase):
    def test_store_roundtrip_style_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            store = ProjectStore()
            project = Project.create("新项目")
            project.style_model = 2
            store.save(project, path)
            self.assertEqual(2, store.load(path).style_model)
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["style_model"]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(1, store.load(path).style_model)

    def test_store_roundtrip_show_speaker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            store = ProjectStore()
            project = Project.create("说话人")
            project.show_speaker = False
            store.save(project, path)
            self.assertFalse(store.load(path).show_speaker)
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["show_speaker"]
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(store.load(path).show_speaker)

    def test_oversized_save_never_replaces_the_existing_project(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            store = ProjectStore()
            store.save(Project.create("Existing"), path)
            before = path.read_bytes()
            with patch.object(store, "MAX_BYTES", 100):
                with self.assertRaisesRegex(ValueError, "项目文件超过"):
                    store.save(Project.create("Too large"), path)
            self.assertEqual(before, path.read_bytes())

    def test_saved_manual_caption_is_restored_through_the_public_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "原始字幕.png"
            Image.new("RGB", (20, 20), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]
            asset.subtitles[0].text = "人工修改后的字幕"
            asset.subtitles[0].source = SubtitleSource.MANUAL
            project = Project.create("测试项目", [asset])
            project_path = root / "test.subtitle-project.json"

            store = ProjectStore()
            store.save(project, project_path)
            restored = store.load(project_path)

        self.assertEqual("测试项目", restored.name)
        self.assertEqual(source.resolve(), restored.assets[0].source_path)
        self.assertEqual("人工修改后的字幕", restored.assets[0].subtitles[0].text)
        self.assertEqual(SubtitleSource.MANUAL, restored.assets[0].subtitles[0].source)

    def test_corrupted_primary_project_recovers_the_last_readable_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "recover.subtitle-project.json"
            project = Project.create("第一版")
            store = ProjectStore()
            store.save(project, project_path)
            project.name = "第二版"
            store.save(project, project_path)
            project_path.write_text("{corrupted", encoding="utf-8")

            restored = store.load(project_path)

        self.assertEqual("第一版", restored.name)

    def test_layout_and_style_overrides_survive_project_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "布局字幕.png"
            Image.new("RGB", (20, 20), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]
            subtitle = asset.subtitles[0]
            subtitle.manual_position_ratio = (0.35, 0.72)
            subtitle.rotation = 8.5
            subtitle.style_overrides = {"font_size": 72, "show_background": True}
            project_path = root / "layout.subtitle-project.json"
            store = ProjectStore()
            store.save(Project.create("布局项目", [asset]), project_path)

            restored = store.load(project_path).assets[0].subtitles[0]

        self.assertEqual((0.35, 0.72), restored.manual_position_ratio)
        self.assertEqual(8.5, restored.rotation)
        self.assertEqual(
            {"font_size": 72, "show_background": True}, restored.style_overrides
        )

    def test_project_from_a_newer_schema_is_rejected_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.subtitle-project.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 99,
                        "project_id": "future",
                        "name": "未来项目",
                        "created_at": "2026-01-01T00:00:00+09:00",
                        "updated_at": "2026-01-01T00:00:00+09:00",
                        "assets": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "版本"):
                ProjectStore().load(path)

    def test_active_export_manifest_path_survives_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = Project.create("任务恢复")
            project.active_export_manifest = str(root / "active-export.json")
            path = root / "project.subtitle-project.json"

            ProjectStore().save(project, path)
            restored = ProjectStore().load(path)

        self.assertEqual(project.active_export_manifest, restored.active_export_manifest)

    def test_status_before_missing_source_survives_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "字幕.png"
            Image.new("RGB", (20, 20), "white").save(source)
            asset = ImportService().import_paths([source]).assets[0]
            asset.unavailable_previous_status = asset.caption_status
            asset.caption_status = CaptionStatus.UNREADABLE
            path = root / "project.subtitle-project.json"

            ProjectStore().save(Project.create("缺失状态", [asset]), path)
            restored = ProjectStore().load(path).assets[0]

        self.assertEqual("ready", restored.unavailable_previous_status.value)


if __name__ == "__main__":
    unittest.main()
