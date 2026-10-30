"""Run shared core and React boundary tests without importing the retired Qt UI."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
suite = unittest.TestSuite()
for file in sorted((ROOT / "tests").glob("test_*.py")):
    if file.name in {"test_ui_flow.py", "test_smoke_mode.py"}:
        continue
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(file.stem))
raise SystemExit(0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1)
