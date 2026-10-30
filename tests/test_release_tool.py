import base64
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from subtitle_app import __version__
from subtitle_app.updater import NOTES_LIMIT

ROOT = Path(__file__).resolve().parents[1]
VERSIONED = ("src/subtitle_app/__init__.py", "src/subtitle_app/update_key.py", "pyproject.toml", "packaging/installer.iss", "packaging/version_info.txt")
spec = importlib.util.spec_from_file_location("release_tool", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def copies(root: Path) -> set[str]:
    """Every version string the build reads, in the formats each file uses."""
    found = {release.read_version(root)}
    found |= set(release.re.findall(r'(?m)^version = "([^"]*)"', (root / "pyproject.toml").read_text(encoding="utf-8")))
    found |= set(release.re.findall(r'#define AppVersion "([^"]*)"', (root / "packaging/installer.iss").read_text(encoding="utf-8")))
    info = (root / "packaging/version_info.txt").read_text(encoding="utf-8")
    found |= {".".join(m[:3]) for m in release.re.findall(r"(?:filevers|prodvers)=\((\d+), (\d+), (\d+), 0\)", info)}
    found |= set(release.re.findall(r"u'(?:FileVersion|ProductVersion)', u'([^']*)'", info))
    return found


class ReleaseToolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in VERSIONED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)

    def tearDown(self):
        self.temp.cleanup()

    def test_every_copy_of_the_version_matches(self):
        self.assertEqual(copies(ROOT), {__version__})

    def test_set_version_rewrites_every_copy(self):
        release.set_version(self.root, "1.20.3")
        self.assertEqual(copies(self.root), {"1.20.3"})
        with self.assertRaises(SystemExit):
            release.set_version(self.root, "1.2")

    def test_check_needs_matching_tag_and_a_public_key(self):
        release.set_version(self.root, "1.2.3")
        release.write_public_key(self.root, base64.b64encode(bytes(32)).decode())
        self.assertEqual(release.check(self.root, "v1.2.3"), "1.2.3")
        for tag in ("v1.2.4", "1.2.3", "v1.2.3-rc1"):
            with self.subTest(tag=tag), self.assertRaises(SystemExit):
                release.check(self.root, tag)
        release.write_public_key(self.root, "")
        with self.assertRaisesRegex(SystemExit, "keygen"):
            release.check(self.root, "v1.2.3")

    def test_release_notes_become_plain_text(self):
        body = ("## What's Changed\r\n* 应用内自动更新 by @Ver-Max-33 in https://github.com/Ver-Max-33/jian-subtitle/pull/3\r\n"
                "- **修复**多条字幕的顺序\r\n\r\n**Full Changelog**: https://github.com/Ver-Max-33/jian-subtitle/compare/v0.2.0...v0.3.0")
        self.assertEqual(release.plain_notes(body), "• 应用内自动更新\n• 修复多条字幕的顺序")
        self.assertEqual(release.plain_notes("## 新功能\n可以检查更新"), "新功能\n可以检查更新")
        self.assertEqual(release.plain_notes("**Full Changelog**: https://example.com"), "")
        self.assertEqual(len(release.plain_notes("x" * 9000)), NOTES_LIMIT)

    def test_signing_lets_a_mistyped_passphrase_be_entered_again(self):
        results = iter([1, 1, 0])
        with mock.patch.object(release.subprocess, "run", side_effect=lambda *a, **k: SimpleNamespace(returncode=next(results))) as run:
            release._sign("openssl", Path("key.pem"), Path("payload"), Path("signature"))
        self.assertEqual(3, run.call_count)
        with mock.patch.object(release.subprocess, "run", return_value=SimpleNamespace(returncode=1)), self.assertRaisesRegex(SystemExit, "没有发布"):
            release._sign("openssl", Path("key.pem"), Path("payload"), Path("signature"))
