from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError


def bundled_font_dirs() -> list[Path]:
    """Fonts shipped with the app: caption fonts, then the interface font (思源黑体) that captions share."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
        return [base / "fonts", base / "frontend" / "fonts"]
    package = Path(__file__).resolve().parent
    return [package / "resources" / "fonts", package.parents[1] / "frontend" / "public" / "fonts"]


class FontCatalog:
    """Resolves a visible system font family to the file Pillow needs."""

    def find_path(self, family: str | None) -> Path | None:
        if not family:
            return None
        catalog = self._catalog()
        exact = catalog.get(family.casefold())
        if exact is not None:
            return exact
        requested = family.casefold()
        return next(
            (path for name, path in catalog.items() if requested in name or name in requested),
            None,
        )

    @classmethod
    @lru_cache(maxsize=1)
    def _catalog(cls) -> dict[str, Path]:
        catalog: dict[str, Path] = {}
        for path in cls._font_files():
            font: TTFont | None = None
            try:
                font = TTFont(path, fontNumber=0, lazy=True)
                name_table = font["name"]
                names = [
                    record.toUnicode().strip()
                    for record in name_table.names
                    if record.nameID in {1, 16} and record.toUnicode().strip()
                ]
            except (OSError, KeyError, TTLibError, UnicodeError):
                continue
            finally:
                if font is not None:
                    font.close()
            for name in names:
                catalog.setdefault(name.casefold(), path)
        return catalog

    @staticmethod
    def _font_files() -> list[Path]:
        directories = [
            *bundled_font_dirs(),
            Path("C:/Windows/Fonts"),
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
        ]
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            directories.append(Path(local_app_data) / "Microsoft/Windows/Fonts")
        extensions = {".ttf", ".ttc", ".otf", ".otc"}
        paths: list[Path] = []
        seen: set[Path] = set()
        for directory in directories:
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if path.suffix.lower() in extensions and path not in seen:
                    seen.add(path)
                    paths.append(path)
        return paths
