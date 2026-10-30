import tempfile
import unittest
from pathlib import Path

from subtitle_app.models import StyleSettings
from subtitle_app.preset_store import PresetStore


class PresetStoreTests(unittest.TestCase):
    def test_custom_preset_and_default_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "presets.json"
            store = PresetStore(path)
            style = StyleSettings(font_size=76, effect="shadow")

            store.save("我的旁白", style)
            store.set_default("我的旁白")
            restored = PresetStore(path)

        self.assertEqual(76, restored.list()["我的旁白"].font_size)
        self.assertEqual("shadow", restored.default_style().effect)

    def test_deleting_default_preset_also_clears_default_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PresetStore(Path(directory) / "presets.json")
            store.save("临时", StyleSettings(font_size=42))
            store.set_default("临时")

            store.delete("临时")

        self.assertEqual({}, store.list())
        self.assertIsNone(store.default_style())

    def test_renaming_default_preset_preserves_style_and_default_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PresetStore(Path(directory) / "presets.json")
            store.save("旧名称", StyleSettings(font_size=64, effect="glow"))
            store.set_default("旧名称")

            store.rename("旧名称", "新名称")
            restored = PresetStore(Path(directory) / "presets.json")

        self.assertNotIn("旧名称", restored.list())
        self.assertEqual(64, restored.list()["新名称"].font_size)
        self.assertEqual("新名称", restored.default_name)

    def test_renaming_does_not_silently_overwrite_another_preset(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PresetStore(Path(directory) / "presets.json")
            store.save("甲", StyleSettings(font_size=48))
            store.save("乙", StyleSettings(font_size=72))

            with self.assertRaises(ValueError):
                store.rename("甲", "乙")

        self.assertEqual(48, store.list()["甲"].font_size)
        self.assertEqual(72, store.list()["乙"].font_size)


if __name__ == "__main__":
    unittest.main()
