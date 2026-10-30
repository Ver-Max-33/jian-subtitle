import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_proxy_wheel", ROOT / "scripts/build_proxy_wheel.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ProxyWheelTest(unittest.TestCase):
    def test_same_bytes_on_every_os(self):
        # requirements-win.lock pins this wheel's hash, and CI builds it on Windows.
        files = {"proxy_tools/__init__.py": b"x = 1\n", "proxy_tools-0.1.0.dist-info/RECORD": b""}
        built = []
        with tempfile.TemporaryDirectory() as temp:
            for platform in ("darwin", "win32"):
                destination = Path(temp) / f"{platform}.whl"
                with mock.patch.object(sys, "platform", platform):
                    builder.write_wheel(destination, files)
                built.append(destination.read_bytes())
        self.assertEqual(built[0], built[1])
