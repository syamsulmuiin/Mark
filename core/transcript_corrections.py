"""Bounded, scoped transcript correction and aggregation helpers.

Corrections are display/history-only. No provider vocabulary field is sent because
this repository does not advertise a supported contract for one.
"""

from __future__ import annotations

import re
from collections import OrderedDict

_SENSITIVE = re.compile(
    r"(?ix)(?:\b(?:password|passcode|otp|pin|token|secret|api[ _-]?key)\b|"
    r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|\+?\d[\d ()-]{7,}\d|\b[a-z0-9]{20,}\b)"
)
_CORRECTION_PATTERNS = (
    re.compile(r"(?i)(?:maksud saya|yang benar|seharusnya)\s+([^,.;!?]+?)\s*,?\s*bukan\s+([^,.;!?]+)"),
    re.compile(r"(?i)([^,.;!?]+?)\s*,?\s*bukan\s+([^,.;!?]+)"),
)


def _safe_term(value: str) -> str:
    value = " ".join(str(value or "").split()).strip(" .,;:!?\"'")
    return value if value and len(value) <= 80 and not _SENSITIVE.search(value) else ""


class ScopedTranscriptCorrections:
    def __init__(self, scope: str, max_entries: int = 16):
        self.scope = str(scope or "session").strip() or "session"
        self.max_entries = max(1, int(max_entries))
        self._mapping: OrderedDict[str, str] = OrderedDict()
        self._partial = ""

    def aggregate(self, fragment: str) -> str:
        clean = " ".join(str(fragment or "").split()).strip()
        if not clean:
            return self._partial
        if not self._partial or clean.startswith(self._partial):
            self._partial = clean
        elif self._partial.startswith(clean):
            pass
        else:
            self._partial = f"{self._partial} {clean}".strip()
        return self._partial

    def learn(self, source: str, target: str) -> bool:
        source, target = _safe_term(source), _safe_term(target)
        if not source or not target or source.casefold() == target.casefold():
            return False
        self._mapping.pop(source.casefold(), None)
        self._mapping[source.casefold()] = target
        while len(self._mapping) > self.max_entries:
            self._mapping.popitem(last=False)
        return True

    def learn_from_conversation(self, text: str) -> bool:
        clean = " ".join(str(text or "").split())
        for pattern in _CORRECTION_PATTERNS:
            match = pattern.search(clean)
            if not match:
                continue
            # "halaman, bukan elemen" means provider/source=elemen, target=halaman.
            first, second = (_safe_term(match.group(1)), _safe_term(match.group(2)))
            if "bukan" in match.group(0).casefold():
                return self.learn(second, first)
            return self.learn(first, second)
        return False

    def correct(self, text: str) -> str:
        result = str(text or "")
        for source, target in self._mapping.items():
            result = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", target, result, flags=re.IGNORECASE)
        return result

    def mapping(self) -> dict[str, str]:
        return dict(self._mapping)
