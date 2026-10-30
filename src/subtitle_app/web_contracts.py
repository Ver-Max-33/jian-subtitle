from __future__ import annotations

import math
import re

from .models import StyleSettings
from .web_fonts import font_entries


class CommandError(ValueError):
    def __init__(self, code: str, message: str, affected_ids: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.affected_ids = affected_ids or []


def text_value(value, label: str, maximum: int = 10000, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value or (not empty and not value.strip()):
        raise CommandError("INVALID_INPUT", f"{label}不合法（最多 {maximum} 字）")
    return value


def number(value, low: float, high: float, label: str, integer: bool = False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
        raise CommandError("INVALID_INPUT", f"{label}应为 {low:g}–{high:g}" + (" 的整数" if integer else ""))
    return int(value) if integer else float(value)


def boolean(value, label: str) -> bool:
    if type(value) is not bool:
        raise CommandError("INVALID_INPUT", f"{label}应为开关值")
    return value


def choice(value, values, label: str):
    if value not in values:
        raise CommandError("INVALID_INPUT", f"{label}无效")
    return value


def rgba(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise CommandError("INVALID_INPUT", "颜色应包含 RGBA 四个分量")
    return tuple(number(x, 0, 255, "颜色", True) for x in value)


def style_patch(values: dict) -> dict:
    if not isinstance(values, dict):
        raise CommandError("INVALID_INPUT", "样式必须是对象")
    result = {}
    # Outline and spacing are image pixels: a 4K caption needs ~18 px of outline, tight titles need negative spacing.
    # Fractions come from converting between picture sizes (spec 4.2).
    ranges = {"font_size": (8, 512), "stroke_width": (0, 200), "line_spacing": (0, 200), "letter_spacing": (-200, 200)}
    for key, value in values.items():
        if key in ranges:
            result[key] = round(number(value, *ranges[key], key), 2)
        elif key == "skew":
            result[key] = number(value, 0, 30, "倾斜角度")
        elif key in {"text_color", "stroke_color", "background_color"}:
            result[key] = rgba(value)
        elif key in {"show_background", "safe_edge"}:
            result[key] = boolean(value, key)
        elif key == "max_width":
            result[key] = number(value, 0.1, 1, "最大宽度")
        elif key == "alignment":
            result[key] = choice(value, ("left", "center", "right"), "对齐")
        elif key == "effect":
            result[key] = choice(value, ("none", "shadow", "glow", "outline", "relief"), "文字效果")
        elif key == "font_id":
            font = font_entries().get(value)
            if not font:
                raise CommandError("FONT_MISSING", "字体已不可用，请重新选择")
            result.update(font_path=font["path"], font_family=font["family"], font_index=font["index"], font_weight=font["weight"])
        else:
            raise CommandError("INVALID_INPUT", f"不允许修改样式字段：{key}")
    return result


FONT_IDENTITY = ("font_path", "font_family", "font_index", "font_weight")


def validate_style_values(values: dict) -> StyleSettings:
    """Range-check a stored style. The font itself may be missing on this computer; that is checked separately."""
    unknown = set(values) - set(StyleSettings.__dataclass_fields__)
    if unknown:
        raise CommandError("INVALID_INPUT", f"不允许修改样式字段：{sorted(unknown)[0]}")
    style = StyleSettings.from_mapping(values)
    safe = style.to_mapping()
    for key in (*FONT_IDENTITY, "reference_edge"):
        safe.pop(key)
    style_patch(safe)
    if style.reference_edge is not None:
        number(style.reference_edge, 64, 16384, "参考尺寸", True)
    number(style.font_index, 0, 31, "字体字面", True)
    if style.font_weight is not None:
        number(style.font_weight, 1, 1000, "字重", True)
    return style


def validate_stored_style(values: dict) -> None:
    style = validate_style_values(values)
    if style.font_path and not any(f["path"] == style.font_path and f["index"] == style.font_index for f in font_entries().values()):
        # Keep unavailable font names for an explicit replacement, never open this path.
        raise CommandError("FONT_MISSING", "项目字体不可用，请选择替代字体")


def windows_filename(value: str) -> bool:
    return bool(value and len(value.encode("utf-16-le")) <= 480 and not re.search(r'[<>:"/\\|?*\x00-\x1f]', value) and not value.endswith((" ", ".")) and not re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", value, re.I))
