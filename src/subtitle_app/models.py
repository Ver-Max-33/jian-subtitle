from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from .filename_classifier import FilenameKind


class SubtitleSource(StrEnum):
    FILENAME_AUTO = "filename_auto"
    MANUAL = "manual"
    IMPORTED = "imported"


class CaptionStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    NEEDS_REVIEW = "needs_review"
    NO_CAPTION = "no_caption"
    UNREADABLE = "unreadable"


class JobItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class NamingMode(StrEnum):
    ORIGINAL = "original"
    SEQUENCE = "sequence"


@dataclass(frozen=True, slots=True)
class StyleSettings:
    font_size: int = 110
    font_family: str | None = None
    font_path: str | None = None
    text_color: tuple[int, int, int, int] = (255, 255, 255, 255)
    stroke_width: int = 4
    stroke_color: tuple[int, int, int, int] = (0, 0, 0, 255)
    line_spacing: int = 10
    show_background: bool = False
    background_color: tuple[int, int, int, int] = (0, 0, 0, 160)
    effect: str = "none"
    max_width: float = 0.88
    alignment: str = "center"
    letter_spacing: int = 0
    font_index: int = 0
    safe_edge: bool = True
    # Variable fonts only: the `wght` value; None means the face's Regular weight.
    font_weight: int | None = None
    # Faux italic in degrees, top leaning right; the outline stays even (see RenderService).
    skew: float = 0.0
    # Short edge the pixel sizes are meant for; None keeps fixed pixels (projects from before 2026-10-30).
    reference_edge: int | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "font_size": self.font_size,
            "font_family": self.font_family,
            "font_path": self.font_path,
            "text_color": self.text_color,
            "stroke_width": self.stroke_width,
            "stroke_color": self.stroke_color,
            "line_spacing": self.line_spacing,
            "show_background": self.show_background,
            "background_color": self.background_color,
            "effect": self.effect,
            "max_width": self.max_width,
            "alignment": self.alignment,
            "letter_spacing": self.letter_spacing,
            "font_index": self.font_index,
            "safe_edge": self.safe_edge,
            "font_weight": self.font_weight,
            "skew": self.skew,
            "reference_edge": self.reference_edge,
        }

    @classmethod
    def from_mapping(cls, values: dict[str, object] | None) -> "StyleSettings":
        if not values:
            return cls()
        color_keys = {"text_color", "stroke_color", "background_color"}
        normalized = {
            key: tuple(value) if key in color_keys and isinstance(value, list) else value
            for key, value in values.items()
            if key in cls.__dataclass_fields__
        }
        return cls(**normalized)


def stacked_position(index: int, count: int) -> tuple[float, float]:
    """Where a caption sits before anyone places it: stacked up from the bottom in reading order, the first one on
    top, as 智能避让 places them (2026-11-13; the first used to sit lowest, so a dialogue read upwards)."""
    return 0.5, max(0.12, 0.86 - (count - 1 - index) * 0.12)


@dataclass(frozen=True, slots=True)
class CaptionRenderRequest:
    text: str
    position_ratio: tuple[float, float] = (0.5, 0.88)
    rotation: float = 0.0
    style: StyleSettings | None = None


@dataclass(slots=True)
class ExportJobItem:
    source_path: Path
    output_path: Path
    captions: list[CaptionRenderRequest]
    style: StyleSettings
    copy_original: bool = False
    preserve_metadata: bool = True
    status: JobItemStatus = JobItemStatus.PENDING
    error_code: str | None = None
    error_message: str | None = None
    # None: 保持原格式, the source's own character (a lossless WebP stays lossless).
    quality: int | None = 95
    jpeg_background: tuple[int, int, int] = (255, 255, 255)
    source_fingerprint: str | None = None
    output_fingerprint: str | None = None


@dataclass(slots=True)
class ExportJobResult:
    items: list[ExportJobItem]
    success_count: int
    failed_count: int
    skipped_count: int
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class ExportOptions:
    output_dir: Path
    naming_mode: NamingMode = NamingMode.ORIGINAL
    start_number: int = 1
    digits: int = 2
    prefix: str = ""
    suffix: str = ""
    include_no_caption: bool = True
    preserve_format: bool = True
    preserve_metadata: bool = True
    image_format: str = "original"
    quality: int | None = 95
    jpeg_background: tuple[int, int, int] = (255, 255, 255)


@dataclass(slots=True)
class ExportPlan:
    items: list[ExportJobItem]
    warnings: list[str] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SubtitleItem:
    id: str
    text: str
    source: SubtitleSource
    speaker_id: str | None = None
    manual_position_ratio: tuple[float, float] | None = None
    rotation: float = 0.0
    style_overrides: dict[str, object] = field(default_factory=dict)
    auto_position_ratio: tuple[float, float] | None = None


@dataclass(slots=True)
class Asset:
    id: str
    source_path: Path
    filename: str
    created_at: datetime
    modified_at: datetime
    import_order: int
    filename_kind: FilenameKind
    caption_status: CaptionStatus
    subtitles: list[SubtitleItem] = field(default_factory=list)
    unavailable_previous_status: CaptionStatus | None = None
    # When the camera or screenshot tool says the picture was taken (EXIF); survives copying, unlike file times.
    taken_at: datetime | None = None
    # Upright pixel size (EXIF rotation applied), read from the file header at import.
    width: int | None = None
    height: int | None = None


@dataclass(slots=True)
class ImportResult:
    assets: list[Asset]
    issues: list["ImportIssue"] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ImportIssue:
    path: Path
    code: str
    message: str


@dataclass(slots=True)
class Project:
    schema_version: int
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    assets: list[Asset] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)
    default_style: dict[str, object] = field(default_factory=dict)
    export_options: dict[str, object] = field(default_factory=dict)
    last_page: str = "import_check"
    active_export_manifest: str | None = None
    revision: int = 0
    # How `assets` is ordered; the list order itself is what export numbering, navigation and the list show.
    order_mode: str = "time"
    # 2: `default_style` is the unified style and overrides are real exceptions (2026-10-30). Older files fold once on open.
    style_model: int = 1
    # 「在字幕前显示说话人」: preview, preflight and export add 「小林：」 when on (spec 4.7).
    show_speaker: bool = True

    @classmethod
    def create(cls, name: str, assets: list[Asset] | None = None) -> "Project":
        from uuid import uuid4

        now = datetime.now().astimezone()
        return cls(1, str(uuid4()), name, now, now, list(assets or []))
