from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .models import StyleSettings


class PresetStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._presets: dict[str, StyleSettings] = {}
        self._default_name: str | None = None
        self._load()

    def list(self) -> dict[str, StyleSettings]:
        return dict(self._presets)

    def save(self, name: str, style: StyleSettings) -> None:
        normalized = name.strip()
        if not normalized:
            raise ValueError("预设名称不能为空")
        self._presets[normalized] = style
        self._write()

    def delete(self, name: str) -> None:
        self._presets.pop(name, None)
        if self._default_name == name:
            self._default_name = None
        self._write()

    def rename(self, old_name: str, new_name: str) -> None:
        normalized = new_name.strip()
        if not normalized:
            raise ValueError("预设名称不能为空")
        if old_name not in self._presets:
            raise KeyError(f"没有这个自定义预设：{old_name}")
        if normalized == old_name:
            return
        if normalized in self._presets:
            raise ValueError(f"预设“{normalized}”已存在")
        self._presets[normalized] = self._presets.pop(old_name)
        if self._default_name == old_name:
            self._default_name = normalized
        self._write()

    def set_default(self, name: str | None) -> None:
        if name is not None and name not in self._presets:
            raise KeyError(f"没有这个自定义预设：{name}")
        self._default_name = name
        self._write()

    def default_style(self) -> StyleSettings | None:
        return self._presets.get(self._default_name) if self._default_name else None

    @property
    def default_name(self) -> str | None:
        return self._default_name

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != self.SCHEMA_VERSION:
                return
            presets = payload.get("presets", {})
            if not isinstance(presets, dict):
                return
            self._presets = {
                str(name): StyleSettings.from_mapping(values)
                for name, values in presets.items()
                if isinstance(values, dict)
            }
            default_name = payload.get("default_name")
            self._default_name = (
                str(default_name) if default_name in self._presets else None
            )
        except (OSError, ValueError, TypeError):
            self._presets = {}
            self._default_name = None

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "default_name": self._default_name,
            "presets": {
                name: style.to_mapping() for name, style in self._presets.items()
            },
        }
        temporary = self._path.with_name(
            f".{self._path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)
