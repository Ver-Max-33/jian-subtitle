from __future__ import annotations

from pathlib import Path


class SpeakerImporter:
    def load(self, path: Path) -> tuple[str, ...]:
        source = Path(path)
        text: str | None = None
        last_error: UnicodeDecodeError | None = None
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = source.read_text(encoding=encoding)
                break
            except UnicodeDecodeError as error:
                last_error = error
        if text is None:
            if last_error is not None:
                raise last_error
            raise OSError(f"无法读取说话人文件：{source}")
        unique: list[str] = []
        seen: set[str] = set()
        for line in text.splitlines():
            name = line.strip()
            if name and name not in seen:
                seen.add(name)
                unique.append(name)
        return tuple(unique)
