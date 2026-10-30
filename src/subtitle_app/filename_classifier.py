from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class FilenameKind(StrEnum):
    CAPTION = "caption"
    TIMESTAMP_OR_SEQUENCE = "timestamp_or_sequence"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FilenameClassification:
    kind: FilenameKind
    caption_text: str | None = None


class FilenameClassifier:
    """Turns a filename into a caption candidate without touching the file."""

    _NON_CAPTION_PATTERNS = tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\d+",
            r"\d{8}[_-]\d{6}",
            r"\d{4}[-_.]\d{2}[-_.]\d{2}(?:[ T_-]\d{2}[-_.:]\d{2}[-_.:]\d{2})?",
            r"(?:IMG|DSC|PXL)[_-](?=[A-Z0-9_-]*\d)[A-Z0-9_-]+",
        )
    )

    def classify(self, filename: str) -> FilenameClassification:
        stem = Path(filename).stem.strip()
        if any(pattern.fullmatch(stem) for pattern in self._NON_CAPTION_PATTERNS):
            return FilenameClassification(FilenameKind.TIMESTAMP_OR_SEQUENCE)
        if any("\u3400" <= char <= "\u9fff" for char in stem):
            return FilenameClassification(FilenameKind.CAPTION, stem)
        return FilenameClassification(FilenameKind.UNKNOWN)
