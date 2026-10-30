import tempfile
import unittest
from pathlib import Path

from subtitle_app.speaker_importer import SpeakerImporter


class SpeakerImporterTests(unittest.TestCase):
    def test_utf8_bom_file_removes_blank_lines_and_duplicate_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "speakers.txt"
            path.write_text("阿明\n\n小雨\n阿明\n", encoding="utf-8-sig")

            speakers = SpeakerImporter().load(path)

        self.assertEqual(("阿明", "小雨"), speakers)


if __name__ == "__main__":
    unittest.main()
