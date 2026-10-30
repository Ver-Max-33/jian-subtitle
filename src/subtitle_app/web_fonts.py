from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError

from .font_catalog import FontCatalog, bundled_font_dirs


def _chinese_name(names) -> str | None:
    """Users search 微软雅黑/黑体, not Microsoft YaHei/SimHei; prefer Simplified Chinese records."""
    for platform, language in ((3, 0x804), (1, 33), (3, 0x1004), (3, 0x404), (3, 0xC04), (1, 19)):
        for name_id in (16, 1):
            for record in names.names:
                if (record.nameID, record.platformID, record.langID) == (name_id, platform, language):
                    try:
                        text = record.toUnicode().strip()
                    except UnicodeError:
                        continue
                    if text:
                        return text
    return None


REGULAR_WEIGHT = 400


@lru_cache(maxsize=1)
def bundled_labels() -> dict[str, str]:
    """Display names of the bundled fonts, keyed by file name (fonts.lock.json is the single source)."""
    labels = {}
    for directory in bundled_font_dirs():
        lock = directory / "fonts.lock.json"
        if lock.is_file():
            data = json.loads(lock.read_text(encoding="utf-8"))
            for font in data.get("fonts", []) + data.get("shared", []):
                labels[Path(font["file"]).name] = font["label"]
    return labels


@lru_cache(maxsize=1)
def font_entries() -> dict[str, dict]:
    """Every selectable face. Variable fonts list one entry per named weight; static ids stay `path:index`."""
    entries = {}
    bundled = [directory.resolve() for directory in bundled_font_dirs()]
    labels = bundled_labels()
    for path in FontCatalog._font_files():
        is_bundled = any(path.resolve().is_relative_to(directory) for directory in bundled)
        for index in range(32 if path.suffix.lower() in {".ttc", ".otc"} else 1):
            font = None
            stream = None
            try:
                stream = path.open("rb")
                font = TTFont(stream, fontNumber=index, lazy=True)
                names = font["name"]
                family = names.getDebugName(16) or names.getDebugName(1) or path.stem
                label = (labels.get(path.name) if is_bundled else None) or _chinese_name(names) or family
                base = {"family": family, "label": label, "path": str(path), "index": index, "bundled": is_bundled}
                instances = [i for i in font["fvar"].instances if "wght" in i.coordinates] if "fvar" in font else []
                if instances:
                    for instance in instances:
                        weight = round(instance.coordinates["wght"])
                        identifier = hashlib.sha256(f"{path}:{index}:wght={weight}".encode()).hexdigest()[:24]
                        variant = names.getDebugName(instance.subfamilyNameID) or str(weight)
                        entries[identifier] = {"id": identifier, **base, "variant": variant, "weight": weight}
                else:
                    variant = names.getDebugName(17) or names.getDebugName(2) or "Regular"
                    identifier = hashlib.sha256(f"{path}:{index}".encode()).hexdigest()[:24]
                    entries[identifier] = {"id": identifier, **base, "variant": variant, "weight": None}
            except (OSError, KeyError, TTLibError, UnicodeError):
                break
            finally:
                if font is not None:
                    font.close()
                if stream is not None:
                    stream.close()
    return entries


def default_font_id() -> str | None:
    """New projects use the bundled 思源黑体 so exports look the same on every computer."""
    catalog = font_entries()
    bundled = next((key for key, font in catalog.items() if font["bundled"] and font["family"] == "Noto Sans SC" and font["weight"] == REGULAR_WEIGHT), None)
    if bundled:
        return bundled
    for family in ("Microsoft YaHei", "PingFang SC", "Heiti SC", "Noto Sans CJK SC", "Arial"):
        for key, font in catalog.items():
            if font["family"].casefold() == family.casefold() and font["variant"].lower() in {"regular", "normal", "medium"}:
                return key
    return next(iter(catalog), None)


def font_id_resolver():
    """Map a stored style to its entry id. Without a weight, variable fonts resolve to their Regular instance."""
    faces: dict[tuple[str, int], list[tuple[int | None, str]]] = {}
    for key, entry in font_entries().items():
        faces.setdefault((entry["path"], entry["index"]), []).append((entry["weight"], key))

    def resolve(style: dict) -> str | None:
        candidates = faces.get((style.get("font_path"), style.get("font_index", 0)))
        if not candidates:
            return None
        weight = style.get("font_weight")
        exact = next((key for value, key in candidates if value == weight), None)
        if exact is not None:
            return exact
        target = REGULAR_WEIGHT if weight is None else weight
        return min(candidates, key=lambda item: abs((item[0] or REGULAR_WEIGHT) - target))[1]

    return resolve


def font_id_for_style(style: dict) -> str | None:
    return font_id_resolver()(style)


@lru_cache(maxsize=64)
def font_codepoints(path: str, index: int) -> frozenset[int]:
    with TTFont(Path(path), fontNumber=index, lazy=True) as font:
        return frozenset((font.getBestCmap() or {}).keys())
