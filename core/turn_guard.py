"""Per-turn assistant completion identity and duplicate suppression."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> str:
    return _SPACE.sub(" ", _PUNCT.sub("", str(text or "").casefold())).strip()


class AssistantResponseGuard:
    def __init__(self, similarity: float = 0.70):
        self.similarity = similarity
        self._request_id: str | None = None
        self._responses: list[str] = []

    def begin(self, request_id: str | None) -> None:
        request_id = str(request_id or "").strip() or None
        if request_id != self._request_id:
            self._request_id = request_id
            self._responses = []

    def accept(self, text: str) -> bool:
        candidate = _normalize(text)
        if not candidate:
            return False
        for previous in self._responses:
            if candidate == previous or candidate in previous or previous in candidate:
                return False
            if SequenceMatcher(None, candidate, previous).ratio() >= self.similarity:
                return False
        self._responses.append(candidate)
        if len(self._responses) > 8:
            self._responses.pop(0)
        return True

    @property
    def request_id(self) -> str | None:
        return self._request_id
