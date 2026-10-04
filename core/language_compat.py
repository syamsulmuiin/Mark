"""Natural-language compatibility aliases used by runtime safety gates.

Project-facing documentation, comments, logs, and UI text are English-only.
Non-English literals in this module are intentional input aliases so users can
continue speaking naturally in supported languages without changing runtime
behavior.
"""

from __future__ import annotations

import re


_DIAGNOSTIC_INTENT_RE = re.compile(
    r"\b(diagnos(?:a|e|is|tic)?|debug|check|inspect|repair|fix|"
    r"periksa|cek|telusuri|analisis|analis[ai]s|perbaiki)\b",
    re.IGNORECASE,
)

_GENERIC_ERROR_RE = re.compile(
    r"\s*(ada|terdapat|there(?:'s| is))?\s*(potential\s+)?"
    r"(error|bug|masalah|problem)(\s+(nih|ini|lagi))?[.!?]*\s*",
    re.IGNORECASE,
)


def has_explicit_diagnostic_intent(text: str) -> bool:
    """Return whether the utterance explicitly requests diagnostic or repair work."""
    return bool(_DIAGNOSTIC_INTENT_RE.search(text or ""))


def is_generic_error_report(text: str) -> bool:
    """Return whether the utterance only reports a generic problem without detail."""
    return bool(_GENERIC_ERROR_RE.fullmatch(text or ""))


_REPAIR_APPLY_RE = re.compile(
    r"\b(apply|implement|proceed|repair|fix|lakukan|terapkan|perbaiki|lanjutkan)\b", re.IGNORECASE
)
_HIGH_RISK_APPROVAL_RE = re.compile(
    r"\b(approve|approved|setuju|setujui|izinkan|lanjutkan)\b.{0,40}\b(high[ -]?risk|risiko tinggi|resiko tinggi)\b|"
    r"\b(high[ -]?risk|risiko tinggi|resiko tinggi)\b.{0,40}\b(approve|approved|setuju|setujui|izinkan|lanjutkan)\b",
    re.IGNORECASE,
)

def has_explicit_repair_apply_intent(text: str) -> bool:
    """Approval evidence from the user's actual utterance, not model parameters."""
    return bool(_REPAIR_APPLY_RE.search(text or ""))

def has_explicit_high_risk_approval(text: str) -> bool:
    return bool(_HIGH_RISK_APPROVAL_RE.search(text or ""))
