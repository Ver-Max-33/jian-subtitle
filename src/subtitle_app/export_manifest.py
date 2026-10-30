from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from .files import replace_file
from .models import (
    CaptionRenderRequest,
    ExportJobItem,
    ExportPlan,
    JobItemStatus,
    StyleSettings,
)


class ExportManifestStore:
    SCHEMA_VERSION = 1

    def save(
        self,
        items: list[ExportJobItem],
        path: Path,
        *,
        cancelled: bool = False,
    ) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "cancelled": cancelled,
            "items": [self._encode_item(item) for item in items],
        }
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            replace_file(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def load_incomplete(self, path: Path) -> ExportPlan:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("不支持的导出任务版本")
        items = []
        for values in payload.get("items", []):
            if values.get("status") == JobItemStatus.SUCCESS.value:
                continue
            item = self._decode_item(values)
            item.status = JobItemStatus.PENDING
            item.error_code = None
            item.error_message = None
            items.append(item)
        return ExportPlan(items)

    @staticmethod
    def _encode_item(item: ExportJobItem) -> dict[str, object]:
        return {
            "source_path": str(item.source_path),
            "output_path": str(item.output_path),
            "captions": [
                {
                    "text": caption.text,
                    "position_ratio": caption.position_ratio,
                    "rotation": caption.rotation,
                    "style": caption.style.to_mapping() if caption.style else None,
                }
                for caption in item.captions
            ],
            "style": item.style.to_mapping(),
            "copy_original": item.copy_original,
            "preserve_metadata": item.preserve_metadata,
            "status": item.status.value,
            "error_code": item.error_code,
            "error_message": item.error_message,
            "quality": item.quality,
            "jpeg_background": item.jpeg_background,
            "source_fingerprint": item.source_fingerprint,
            "output_fingerprint": item.output_fingerprint,
        }

    @staticmethod
    def _decode_item(values: dict[str, object]) -> ExportJobItem:
        captions = [
            CaptionRenderRequest(
                str(caption["text"]),
                tuple(caption.get("position_ratio", (0.5, 0.88))),
                float(caption.get("rotation", 0.0)),
                StyleSettings.from_mapping(caption.get("style")),
            )
            for caption in values.get("captions", [])
            if isinstance(caption, dict)
        ]
        return ExportJobItem(
            source_path=Path(str(values["source_path"])),
            output_path=Path(str(values["output_path"])),
            captions=captions,
            style=StyleSettings.from_mapping(values.get("style")),
            copy_original=bool(values.get("copy_original", False)),
            preserve_metadata=bool(values.get("preserve_metadata", True)),
            status=JobItemStatus(str(values.get("status", "pending"))),
            error_code=values.get("error_code"),
            error_message=values.get("error_message"),
            quality=int(values.get("quality", 95)),
            jpeg_background=tuple(values.get("jpeg_background", (255, 255, 255))),
            source_fingerprint=values.get("source_fingerprint"),
            output_fingerprint=values.get("output_fingerprint"),
        )
