"""Built-in caption looks. Classic looks keep the caption's font; font looks bring a bundled font."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import StyleSettings
from .web_fonts import font_entries

WHITE, BLACK = (255, 255, 255, 255), (0, 0, 0, 255)
LAYOUT_KEYS = ("max_width", "alignment", "safe_edge", "font_size")
FONT_KEYS = ("font_family", "font_path", "font_index", "font_weight")


@dataclass(frozen=True, slots=True)
class BuiltinPreset:
    look: StyleSettings
    font_file: str | None = None
    weight: int | None = None
    # Outline as a share of the caption's own font size, so one look fits 1080p and 4K alike.
    stroke_ratio: float | None = None


BUILTIN_PRESETS: dict[str, BuiltinPreset] = {
    "经典": BuiltinPreset(StyleSettings(stroke_width=2, show_background=True)),
    "柔和": BuiltinPreset(StyleSettings(stroke_width=0, show_background=True, background_color=(0, 0, 0, 110))),
    "强调": BuiltinPreset(StyleSettings(stroke_width=4, text_color=(255, 220, 65, 255), effect="shadow")),
    # Measured from a real caption (tests/fixtures/caption-reference.png).
    "粗描边斜体": BuiltinPreset(StyleSettings(text_color=WHITE, stroke_color=BLACK, skew=19.0), "NotoSansSC.ttf", 900, 0.195),
    "纪录片宋体": BuiltinPreset(StyleSettings(text_color=WHITE, stroke_color=(0, 0, 0, 200), effect="shadow"), "NotoSerifSC.ttf", 600, 0.035),
    "文楷叙事": BuiltinPreset(StyleSettings(text_color=WHITE, stroke_color=(20, 20, 20, 255)), "LXGWWenKai-Regular.ttf", None, 0.05),
    "书法标题": BuiltinPreset(StyleSettings(text_color=WHITE, stroke_color=BLACK), "MaShanZheng-Regular.ttf", None, 0.08),
}


def builtin_presets() -> dict[str, BuiltinPreset]:
    return BUILTIN_PRESETS


def bundled_face(font_file: str, weight: int | None) -> dict:
    for entry in font_entries().values():
        if entry["bundled"] and Path(entry["path"]).name == font_file and entry["weight"] == weight:
            return entry
    raise LookupError(font_file)


def preset_card(name: str) -> dict:
    """What the editor needs to show a built-in look and tell whether a caption currently wears it."""
    preset = BUILTIN_PRESETS[name]
    look = preset.look
    card = {"name": name, "fontLabel": None, "fontId": None, "textColor": list(look.text_color), "showBackground": look.show_background,
            "backgroundAlpha": look.background_color[3], "effect": look.effect, "skew": look.skew,
            "strokeRatio": preset.stroke_ratio, "strokeWidth": None if preset.stroke_ratio is not None else look.stroke_width}
    if preset.font_file is not None:
        try:
            face = bundled_face(preset.font_file, preset.weight)
        except LookupError:
            return card
        card.update(fontLabel=face["label"], fontId=face["id"])
    return card


def apply_builtin(name: str, current: dict) -> dict:
    """Style overrides for a caption whose effective style is `current`; its layout and size stay unchanged."""
    preset = BUILTIN_PRESETS[name]
    style = preset.look.to_mapping()
    for key in LAYOUT_KEYS:
        style.pop(key)
    if preset.font_file is None:
        for key in FONT_KEYS:
            style.pop(key)
    else:
        face = bundled_face(preset.font_file, preset.weight)
        style.update(font_path=face["path"], font_family=face["family"], font_index=face["index"], font_weight=face["weight"])
    if preset.stroke_ratio is not None:
        style["stroke_width"] = round(preset.stroke_ratio * float(current["font_size"]))
    return style
