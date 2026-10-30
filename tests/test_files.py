import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from subtitle_app import files


class ReplaceFileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source, self.target = root / "new.json", root / "project.json"
        self.source.write_text("new"); self.target.write_text("old")

    def tearDown(self):
        self.temp.cleanup()

    def blocked(self, times):
        """os.replace that fails like Windows while antivirus or the indexer still holds the target."""
        real, calls = os.replace, []
        def replace(source, target):
            calls.append(target)
            if len(calls) <= times:
                raise PermissionError(13, "Access is denied")
            real(source, target)
        return replace, calls

    def test_windows_retries_while_the_target_is_briefly_held(self):
        replace, calls = self.blocked(3)
        with mock.patch.object(files.os, "replace", replace), mock.patch.object(files.time, "sleep"):
            files.replace_file(self.source, self.target, windows=True)
        self.assertEqual("new", self.target.read_text())
        self.assertEqual(4, len(calls))

    def test_gives_up_with_the_error_when_the_target_stays_held(self):
        replace, _ = self.blocked(100)
        with mock.patch.object(files.os, "replace", replace), mock.patch.object(files.time, "sleep"):
            with self.assertRaises(PermissionError):
                files.replace_file(self.source, self.target, windows=True)
        self.assertEqual("old", self.target.read_text())

    def test_other_systems_do_not_retry(self):
        replace, calls = self.blocked(1)
        with mock.patch.object(files.os, "replace", replace), self.assertRaises(PermissionError):
            files.replace_file(self.source, self.target, windows=False)
        self.assertEqual(1, len(calls))
