from __future__ import annotations

import re


class CaptionParser:
    """Parses caption text without splitting natural-language whitespace."""

    def parse(self, text: str) -> tuple[str, ...]:
        cleaned = text.strip()
        if self._is_complete_multicaption(cleaned):
            return tuple(
                part.strip().replace("#", "\n")
                for part in re.findall(r"【([^【】]+)】", cleaned)
            )
        return (cleaned.replace("#", "\n"),) if cleaned else ()

    def requires_review(self, text: str) -> bool:
        cleaned = text.strip()
        return ("【" in cleaned or "】" in cleaned) and not self._is_complete_multicaption(
            cleaned
        )

    @staticmethod
    def _is_complete_multicaption(text: str) -> bool:
        return re.fullmatch(r"(?:\s*【[^【】]+】\s*)+", text) is not None
