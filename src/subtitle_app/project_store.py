from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .asset_sorter import ORDER_MODES
from .filename_classifier import FilenameKind
from .files import replace_file
from .models import (
    Asset,
    CaptionStatus,
    Project,
    SubtitleItem,
    SubtitleSource,
)


class ProjectStore:
    """Atomically persists projects as readable, versioned JSON."""

    MAX_BYTES = 32 * 1024 * 1024

    def save(self, project: Project, path: Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        project.updated_at = datetime.now().astimezone()
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        backup = destination.with_name(f"{destination.name}.bak")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as file:
                json.dump(self._encode(project), file, ensure_ascii=False, indent=2)
                file.flush()
                if file.tell() > self.MAX_BYTES:
                    raise ValueError("项目文件超过 32 MiB，请拆分图片或减少超长字幕后重试")
                os.fsync(file.fileno())
            if destination.exists():
                shutil.copy2(destination, backup)
            replace_file(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, path: Path) -> Project:
        source = Path(path)
        try:
            return self._load_file(source)
        except (OSError, ValueError, TypeError, KeyError) as primary_error:
            backup = source.with_name(f"{source.name}.bak")
            if not backup.exists():
                raise primary_error
            return self._load_file(backup)

    def _load_file(self, path: Path) -> Project:
        with path.open("r", encoding="utf-8") as file:
            return self._decode(json.load(file))

    def _encode(self, project: Project) -> dict[str, object]:
        return {
            "schema_version": project.schema_version,
            "revision": project.revision,
            "project_id": project.id,
            "name": project.name,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat(),
            "assets": [self._encode_asset(asset) for asset in project.assets],
            "speakers": project.speakers,
            "default_style": project.default_style,
            "export_options": project.export_options,
            "last_page": project.last_page,
            "active_export_manifest": project.active_export_manifest,
            "order_mode": project.order_mode,
            "style_model": project.style_model,
            "show_speaker": project.show_speaker,
        }

    def _encode_asset(self, asset: Asset) -> dict[str, object]:
        return {
            "id": asset.id,
            "source_path": str(asset.source_path),
            "filename": asset.filename,
            "created_at": asset.created_at.isoformat(),
            "modified_at": asset.modified_at.isoformat(),
            "import_order": asset.import_order,
            "taken_at": asset.taken_at.isoformat() if asset.taken_at else None,
            "width": asset.width,
            "height": asset.height,
            "filename_kind": asset.filename_kind.value,
            "caption_status": asset.caption_status.value,
            "unavailable_previous_status": (
                asset.unavailable_previous_status.value
                if asset.unavailable_previous_status
                else None
            ),
            "subtitles": [
                {
                    "id": subtitle.id,
                    "text": subtitle.text,
                    "source": subtitle.source.value,
                    "speaker_id": subtitle.speaker_id,
                    "manual_position_ratio": subtitle.manual_position_ratio,
                    "rotation": subtitle.rotation,
                    "style_overrides": subtitle.style_overrides,
                    "auto_position_ratio": subtitle.auto_position_ratio,
                }
                for subtitle in asset.subtitles
            ],
        }

    def _decode(self, data: dict[str, object]) -> Project:
        schema_version = int(data.get("schema_version", 0))
        if schema_version != 1:
            raise ValueError(f"不支持的项目版本：{schema_version}")
        assets_data = data.get("assets", [])
        if not isinstance(assets_data, list):
            raise ValueError("项目中的 assets 必须是列表")
        return Project(
            schema_version=schema_version,
            revision=int(data.get("revision", 0)),
            id=str(data["project_id"]),
            name=str(data["name"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            updated_at=datetime.fromisoformat(str(data["updated_at"])),
            assets=[self._decode_asset(item) for item in assets_data],
            speakers=[str(name) for name in data.get("speakers", [])],
            default_style=dict(data.get("default_style", {})),
            export_options=dict(data.get("export_options", {})),
            last_page=str(data.get("last_page", "import_check")),
            active_export_manifest=(
                str(data["active_export_manifest"])
                if data.get("active_export_manifest")
                else None
            ),
            # Projects saved before ordering existed keep the order they had; nothing reorders silently.
            order_mode=self._order_mode(data.get("order_mode", "manual")),
            style_model=2 if data.get("style_model") == 2 else 1,
            show_speaker=data.get("show_speaker", True) is not False,
        )

    @staticmethod
    def _order_mode(value: object) -> str:
        if value not in ORDER_MODES:
            raise ValueError(f"项目中的排序方式无效：{value}")
        return str(value)

    @staticmethod
    def _pixels(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 1_000_000:
            raise ValueError(f"项目中的图片尺寸无效：{value}")
        return value

    def _decode_asset(self, data: object) -> Asset:
        if not isinstance(data, dict):
            raise ValueError("项目中的素材必须是对象")
        subtitles_data = data.get("subtitles", [])
        if not isinstance(subtitles_data, list):
            raise ValueError("素材中的 subtitles 必须是列表")
        subtitles = [
            SubtitleItem(
                id=str(item["id"]),
                text=str(item["text"]),
                source=SubtitleSource(str(item["source"])),
                speaker_id=(
                    str(item["speaker_id"]) if item.get("speaker_id") is not None else None
                ),
                manual_position_ratio=(
                    tuple(float(value) for value in item["manual_position_ratio"])
                    if isinstance(item.get("manual_position_ratio"), list)
                    and len(item["manual_position_ratio"]) == 2
                    else None
                ),
                rotation=float(item.get("rotation", 0.0)),
                style_overrides=dict(item.get("style_overrides", {})),
                auto_position_ratio=(tuple(item["auto_position_ratio"]) if item.get("auto_position_ratio") else None),
            )
            for item in subtitles_data
            if isinstance(item, dict)
        ]
        return Asset(
            id=str(data["id"]),
            source_path=Path(str(data["source_path"])),
            filename=str(data["filename"]),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            modified_at=datetime.fromisoformat(str(data["modified_at"])),
            import_order=int(data["import_order"]),
            taken_at=datetime.fromisoformat(str(data["taken_at"])) if data.get("taken_at") else None,
            width=self._pixels(data.get("width")),
            height=self._pixels(data.get("height")),
            filename_kind=FilenameKind(str(data["filename_kind"])),
            caption_status=CaptionStatus(str(data["caption_status"])),
            subtitles=subtitles,
            unavailable_previous_status=(
                CaptionStatus(str(data["unavailable_previous_status"]))
                if data.get("unavailable_previous_status")
                else None
            ),
        )
