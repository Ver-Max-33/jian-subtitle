from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RecentProject:
    path: Path
    name: str
    asset_count: int
    updated_at: datetime
    page: str = "review"


class RecentProjectStore:
    def __init__(self, index_path: Path, limit: int = 10) -> None:
        self._index_path = Path(index_path)
        self._limit = limit

    def list(self) -> list[RecentProject]:
        if not self._index_path.exists():
            return []
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            entries = [
                RecentProject(
                    Path(item["path"]),
                    str(item["name"]),
                    int(item["asset_count"]),
                    datetime.fromisoformat(str(item["updated_at"])),
                    str(item.get("page", "review")),
                )
                for item in data
                if isinstance(item, dict)
            ]
        except (OSError, ValueError, TypeError, KeyError):
            return []
        return [entry for entry in entries if entry.path.exists()][: self._limit]

    def record(self, project: RecentProject) -> None:
        normalized = project.path.resolve()
        entries = [entry for entry in self.list() if entry.path.resolve() != normalized]
        entries.insert(0, project)
        payload = [
            {
                **asdict(entry),
                "path": str(entry.path),
                "updated_at": entry.updated_at.isoformat(),
            }
            for entry in entries[: self._limit]
        ]
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._index_path.with_name(f".{self._index_path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self._index_path)

    def remove(self, path: str) -> None:
        entries = [entry for entry in self.list() if str(entry.path) != path]
        payload = [{"path": str(entry.path), "name": entry.name, "asset_count": entry.asset_count, "updated_at": entry.updated_at.isoformat(), "page": entry.page} for entry in entries]
        temporary = self._index_path.with_name(f".{self._index_path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self._index_path)
