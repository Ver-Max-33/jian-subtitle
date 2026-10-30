from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image

from .asset_sorter import file_times
from .caption_parser import CaptionParser
from .filename_classifier import FilenameClassifier, FilenameKind
from .models import (
    Asset,
    CaptionStatus,
    ImportIssue,
    ImportResult,
    SubtitleItem,
    SubtitleSource,
)


class ImportService:
    """Imports filesystem metadata and filename-derived caption candidates."""

    SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    def __init__(
        self,
        classifier: FilenameClassifier | None = None,
        parser: CaptionParser | None = None,
    ) -> None:
        self._classifier = classifier or FilenameClassifier()
        self._parser = parser or CaptionParser()

    def import_paths(self, paths: list[Path]) -> ImportResult:
        assets: list[Asset] = []
        issues: list[ImportIssue] = []
        seen: set[Path] = set()
        for supplied_path in paths:
            path = Path(supplied_path).resolve()
            if path in seen:
                continue
            seen.add(path)
            if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                issues.append(
                    ImportIssue(
                        path,
                        "IMPORT_UNSUPPORTED_FORMAT",
                        f"不支持的文件格式：{path.suffix or '无扩展名'}",
                    )
                )
                continue
            if not path.is_file():
                issues.append(
                    ImportIssue(path, "SOURCE_MISSING", "源文件不存在或已被移动")
                )
                continue
            classification = self._classifier.classify(path.name)
            readable, taken_at, size = self._inspect(path)
            subtitles = (
                self._build_subtitles(classification.kind, classification.caption_text)
                if readable
                else []
            )
            needs_review = bool(
                readable
                and classification.caption_text
                and self._parser.requires_review(classification.caption_text)
            )
            created_at, modified_at = file_times(path.stat())
            assets.append(
                Asset(
                    id=str(uuid4()),
                    source_path=path,
                    filename=path.name,
                    created_at=created_at,
                    modified_at=modified_at,
                    taken_at=taken_at,
                    width=size[0] if size else None,
                    height=size[1] if size else None,
                    import_order=len(assets),
                    filename_kind=classification.kind,
                    caption_status=(
                        CaptionStatus.UNREADABLE
                        if not readable
                        else CaptionStatus.NEEDS_REVIEW
                        if needs_review
                        else CaptionStatus.READY
                        if subtitles
                        else CaptionStatus.MISSING
                    ),
                    subtitles=subtitles,
                )
            )
        return ImportResult(assets, issues)

    @classmethod
    def _inspect(cls, path: Path) -> tuple[bool, datetime | None, tuple[int, int] | None]:
        """Whether the image decodes, the capture time it records and its upright size, from one open of the file."""
        try:
            with Image.open(path) as image:
                exif = cls._exif(image)
                size = cls.upright_size(image, exif)
                image.verify()
        except (OSError, ValueError, Image.DecompressionBombError):
            return False, None, None
        return True, cls._exif_time(exif), size

    @classmethod
    def upright_size(cls, image: Image.Image, exif: Image.Exif | None = None) -> tuple[int, int]:
        """Header size with EXIF rotation applied, without decoding pixels."""
        exif = exif if exif is not None else cls._exif(image)
        width, height = image.size
        return (height, width) if exif is not None and exif.get(274) in {5, 6, 7, 8} else (width, height)

    @staticmethod
    def _exif(image: Image.Image) -> Image.Exif | None:
        # Only the EXIF already read with the header: Image.getexif() would decode a PNG and void verify().
        raw = image.info.get("exif")
        if not isinstance(raw, bytes):
            return None
        try:
            exif = Image.Exif()
            exif.load(raw)
            exif.get_ifd(0x8769)
        except Exception:  # Metadata in an untrusted file must never block the import itself.
            return None
        return exif

    @staticmethod
    def _exif_time(exif: Image.Exif | None) -> datetime | None:
        """EXIF DateTimeOriginal (or Digitized) with sub-seconds and offset; None when absent or implausible."""
        if exif is None:
            return None
        details = exif.get_ifd(0x8769)
        for stamp, subsec, offset in ((36867, 37521, 36881), (36868, 37522, 36882)):
            raw = details.get(stamp)
            if not isinstance(raw, str):
                continue
            try:
                moment = datetime.strptime(raw.strip()[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
            # A camera without a set clock writes a date like 1970-01-01; skip implausible years before any time zone math,
            # which Windows cannot do for times before 1970.
            if not 1990 <= moment.year <= datetime.now().year + 1:
                continue
            fraction = details.get(subsec)
            if isinstance(fraction, str) and fraction.strip().isdigit():
                moment = moment.replace(microsecond=int((fraction.strip() + "000000")[:6]))
            zone = details.get(offset)
            match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", zone.strip()) if isinstance(zone, str) else None
            if match:
                delta = timedelta(hours=int(match[2]), minutes=int(match[3]))
                moment = moment.replace(tzinfo=timezone(delta if match[1] == "+" else -delta))
            else:
                moment = moment.astimezone()  # Cameras write local wall-clock time.
            return moment
        return None

    def _build_subtitles(
        self, kind: FilenameKind, caption_text: str | None
    ) -> list[SubtitleItem]:
        if kind is not FilenameKind.CAPTION or caption_text is None:
            return []
        return [
            SubtitleItem(str(uuid4()), text, SubtitleSource.FILENAME_AUTO)
            for text in self._parser.parse(caption_text)
        ]

    def reclassify_asset(
        self, asset: Asset, *, overwrite_manual: bool = False
    ) -> bool:
        if not overwrite_manual and any(
            subtitle.source is SubtitleSource.MANUAL for subtitle in asset.subtitles
        ):
            return False
        if asset.caption_status is CaptionStatus.UNREADABLE:
            return False
        classification = self._classifier.classify(asset.filename)
        subtitles = self._build_subtitles(
            classification.kind, classification.caption_text
        )
        asset.filename_kind = classification.kind
        asset.subtitles[:] = subtitles
        if (
            classification.caption_text
            and self._parser.requires_review(classification.caption_text)
        ):
            asset.caption_status = CaptionStatus.NEEDS_REVIEW
        else:
            asset.caption_status = (
                CaptionStatus.READY if subtitles else CaptionStatus.MISSING
            )
        return True
