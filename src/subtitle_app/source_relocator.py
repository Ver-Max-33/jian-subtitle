from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from .import_service import ImportService
from .models import Asset, CaptionStatus


@dataclass(frozen=True, slots=True)
class RelocationResult:
    relocated_count: int
    unresolved_count: int
    ambiguous_count: int


class SourceRelocator:
    def mark_missing(self, assets: list[Asset]) -> int:
        count = 0
        for asset in assets:
            if asset.source_path.is_file():
                continue
            if asset.caption_status is not CaptionStatus.UNREADABLE:
                asset.unavailable_previous_status = asset.caption_status
            asset.caption_status = CaptionStatus.UNREADABLE
            count += 1
        return count

    def relocate(
        self, assets: list[Asset], directory: Path, *, recursive: bool = True
    ) -> RelocationResult:
        root = Path(directory)
        iterator = root.rglob("*") if recursive else root.iterdir()
        by_name: dict[str, list[Path]] = {}
        for path in iterator:
            if path.is_file() and path.suffix.lower() in ImportService.SUPPORTED_EXTENSIONS:
                by_name.setdefault(path.name.casefold(), []).append(path.resolve())
        relocated = 0
        unresolved = 0
        ambiguous = 0
        importer = ImportService()
        for asset in assets:
            if asset.source_path.is_file() and asset.caption_status is not CaptionStatus.UNREADABLE:
                continue
            candidates = [
                path
                for path in by_name.get(asset.filename.casefold(), [])
                if self._is_readable(path)
            ]
            if len(candidates) > 1:
                ambiguous += 1
                continue
            if not candidates:
                unresolved += 1
                continue
            replacement = candidates[0]
            asset.source_path = replacement
            stat = replacement.stat()
            asset.created_at = datetime.fromtimestamp(
                getattr(stat, "st_birthtime", os.path.getctime(replacement))
            ).astimezone()
            asset.modified_at = datetime.fromtimestamp(stat.st_mtime).astimezone()
            previous = asset.unavailable_previous_status
            asset.unavailable_previous_status = None
            if previous is not None:
                asset.caption_status = previous
            elif asset.subtitles:
                asset.caption_status = CaptionStatus.READY
            else:
                asset.caption_status = CaptionStatus.MISSING
                importer.reclassify_asset(asset)
            relocated += 1
        return RelocationResult(relocated, unresolved, ambiguous)

    @staticmethod
    def _is_readable(path: Path) -> bool:
        try:
            with Image.open(path) as image:
                image.verify()
        except (OSError, ValueError):
            return False
        return True
