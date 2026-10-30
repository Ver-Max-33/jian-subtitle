from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from .models import Asset

ORDER_MODES = ("time", "time_desc", "filename", "import", "manual")


class AssetSortMode(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    FILENAME = "filename"
    IMPORT_ORDER = "import_order"


def sorted_assets(assets: list[Asset], mode: AssetSortMode) -> list[Asset]:
    """Return a deterministic order without mutating the supplied collection."""
    if mode is AssetSortMode.CREATED:
        key = lambda asset: (
            asset.created_at,
            asset.import_order,
            str(asset.source_path).casefold(),
        )
    elif mode is AssetSortMode.MODIFIED:
        key = lambda asset: (
            asset.modified_at,
            asset.import_order,
            str(asset.source_path).casefold(),
        )
    elif mode is AssetSortMode.FILENAME:
        key = lambda asset: (
            asset.filename.casefold(),
            asset.import_order,
            str(asset.source_path).casefold(),
        )
    else:
        key = lambda asset: (
            asset.import_order,
            str(asset.source_path).casefold(),
        )
    return sorted(assets, key=key)


def file_times(stat, *, windows: bool | None = None) -> tuple[datetime, datetime]:
    """(created, modified). Only Windows and macOS record creation; elsewhere st_ctime is an inode change, not a creation."""
    windows = os.name == "nt" if windows is None else windows
    created = getattr(stat, "st_birthtime", None)
    if created is None:
        created = stat.st_ctime if windows else stat.st_mtime
    return local_time(created), local_time(stat.st_mtime)


def local_time(timestamp: float) -> datetime:
    """A file time in local time. Windows cannot convert times before 1970 to local time; those stay in UTC."""
    moment = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=timestamp)
    try:
        return moment.astimezone()
    except (OSError, OverflowError, ValueError):
        return moment


def capture_time(asset: Asset) -> datetime:
    """When the picture was taken: the camera's record, else the earlier file time.

    Copying on Windows keeps the modification time but stamps a new creation time, and editing does the reverse,
    so the earlier of the two is the original in both cases.
    """
    return asset.taken_at or min(asset.created_at, asset.modified_at)


def time_source(asset: Asset) -> str:
    if asset.taken_at:
        return "exif"
    return "created" if asset.created_at <= asset.modified_at else "modified"


def natural_key(name: str) -> tuple:
    """画面 9 before 画面 10."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", name) if part)


def order_assets(assets: list[Asset], mode: str) -> list[Asset]:
    if mode == "manual":
        return list(assets)
    if mode in ("time", "time_desc"):
        ordered = sorted(assets, key=lambda a: (capture_time(a), natural_key(a.filename), a.import_order))
        return ordered[::-1] if mode == "time_desc" else ordered
    if mode == "filename":
        return sorted(assets, key=lambda a: (natural_key(a.filename), a.import_order))
    if mode == "import":
        return sorted(assets, key=lambda a: a.import_order)
    raise ValueError(mode)


def time_ties(assets: list[Asset]) -> list[list[str]]:
    """Ids of images that share one capture time: their relative order is only a guess the user should check."""
    groups: dict[datetime, list[str]] = {}
    for asset in assets:
        groups.setdefault(capture_time(asset), []).append(asset.id)
    return [ids for ids in groups.values() if len(ids) > 1]
