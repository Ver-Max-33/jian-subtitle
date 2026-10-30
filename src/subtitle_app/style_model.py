"""The unified style and its exceptions (spec 4.1).

`project.default_style` is the unified style every caption follows; `caption.style_overrides` keeps only
what a caption really does differently. Position fields always belong to the caption itself.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator

from .models import Asset, Project, StyleSettings, SubtitleItem

APPEARANCE_KEYS = ("font_path", "font_family", "font_index", "font_weight", "font_size", "text_color", "stroke_color",
                   "stroke_width", "show_background", "background_color", "effect", "line_spacing", "letter_spacing", "skew")
FONT_KEYS = ("font_path", "font_family", "font_index", "font_weight")
POSITION_KEYS = ("max_width", "alignment", "safe_edge")
# Image pixels, scaled by the picture's short edge when the style has a `reference_edge` (spec 4.2).
SCALED_KEYS = ("font_size", "stroke_width", "line_spacing", "letter_spacing")
REFERENCE_EDGE = 1080


def unified(project: Project) -> dict[str, object]:
    return {**StyleSettings().to_mapping(), **project.default_style}


def captions(project: Project) -> Iterator[SubtitleItem]:
    return (caption for asset in project.assets for caption in asset.subtitles)


def groups(keys: Iterable[str]) -> list[tuple[str, ...]]:
    """Appearance keys as editable units: a font is its file, family, face and weight together."""
    wanted = set(keys)
    result: list[tuple[str, ...]] = []
    for key in APPEARANCE_KEYS:
        group = FONT_KEYS if key in FONT_KEYS else (key,)
        if key in wanted and group not in result:
            result.append(group)
    return result


def _frozen(value):
    return tuple(value) if isinstance(value, list) else value


def _same(a, b) -> bool:
    # Colors arrive as tuples from commands and as lists from saved projects.
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return list(a) == list(b)
    return a == b


def write_unified(project: Project, caption: SubtitleItem, patch: dict) -> None:
    """「全部图片」: the change becomes the unified style, and the caption being edited follows it."""
    for group in groups(patch):
        for key in group:
            caption.style_overrides.pop(key, None)
            if key in patch:
                project.default_style[key] = patch[key]
    caption.style_overrides.update({key: patch[key] for key in POSITION_KEYS if key in patch})
    normalize(project)


def write_override(project: Project, caption: SubtitleItem, patch: dict) -> None:
    """「仅这条」: an exception for this caption only. A reference edge belongs to the unified style alone."""
    caption.style_overrides.update({key: value for key, value in patch.items() if key in APPEARANCE_KEYS or key in POSITION_KEYS})
    normalize(project, [caption])


def normalize(project: Project, items: Iterable[SubtitleItem] | None = None) -> None:
    """Drop exceptions equal to the unified style; kept, they would silently stop following it."""
    base = unified(project)
    for item in captions(project) if items is None else items:
        for group in groups(item.style_overrides):
            if all(_same(item.style_overrides.get(key, base[key]), base[key]) for key in group):
                for key in group:
                    item.style_overrides.pop(key, None)


def restore(items: Iterable[SubtitleItem], keys: Iterable[str] | None = None) -> int:
    """Make captions follow the unified style again; returns how many changed."""
    targets = [key for group in groups(APPEARANCE_KEYS if keys is None else keys) for key in group]
    changed = 0
    for item in items:
        removed = [item.style_overrides.pop(key) for key in targets if key in item.style_overrides]
        changed += bool(removed)
    return changed


def overridden(caption: SubtitleItem) -> list[str]:
    return [key for key in APPEARANCE_KEYS if key in caption.style_overrides]


def short_edge(asset: Asset) -> int | None:
    return min(asset.width, asset.height) if asset.width and asset.height else None


def rescale(values: dict, factor: float) -> dict:
    """The same look for a picture `factor` times the size: only the pixel sizes change."""
    return {key: round(value * factor, 2) if key in SCALED_KEYS else value for key, value in values.items()}


def to_proportional(project: Project) -> int:
    """「改为按画面比例」: the most common short edge becomes the reference, so those pictures look unchanged;
    each exception is converted on its own picture, so it keeps the look it was made for."""
    edges = [edge for edge in map(short_edge, project.assets) if edge]
    counts = Counter(edges)
    reference = next(edge for edge in edges if counts[edge] == max(counts.values())) if edges else REFERENCE_EDGE
    project.default_style["reference_edge"] = reference
    for asset in project.assets:
        edge = short_edge(asset)
        for item in asset.subtitles if edge else []:
            item.style_overrides.update(rescale({k: v for k, v in item.style_overrides.items() if k in SCALED_KEYS}, reference / edge))
    normalize(project)
    return reference


def fold_majority(project: Project) -> None:
    """Once, for projects saved before the unified style: per field, the value most captions show becomes the
    unified one; captions showing anything else keep it as an exception, so nothing on screen changes."""
    items = list(captions(project))
    base = unified(project)
    for group in groups(APPEARANCE_KEYS) if items else []:
        shown = [tuple(_frozen(item.style_overrides.get(key, base[key])) for key in group) for item in items]
        counts = Counter(shown)
        current = tuple(_frozen(base[key]) for key in group)
        most = max(counts.values())
        chosen = current if counts.get(current) == most else next(value for value in shown if counts[value] == most)
        if chosen != current:
            project.default_style.update(zip(group, chosen))
        for item, value in zip(items, shown):
            for key, single in zip(group, value):
                if value == chosen:
                    item.style_overrides.pop(key, None)
                else:
                    item.style_overrides[key] = single
    project.style_model = 2
