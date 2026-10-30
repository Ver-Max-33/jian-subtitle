"""Atomic file replacement that tolerates Windows' brief file locks."""
import os
import time
from pathlib import Path


def replace_file(source: Path, target: Path, *, windows: bool | None = None) -> None:
    """os.replace. On Windows, antivirus or the search indexer may hold a just-written file for a moment,
    and replacing it then fails with PermissionError; wait a little and try again (about 1.6 s in all)."""
    windows = os.name == "nt" if windows is None else windows
    for delay in (0.02, 0.05, 0.1, 0.2, 0.4, 0.8) if windows else ():
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(source, target)
