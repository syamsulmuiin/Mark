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
    r"periksa|cek|telusuri|analisis|analis[ai]s|perbaik(?:i|an))\b",
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
    utterance = text or ""
    # A prohibition is not approval. The Live model may still request the tool,
    # but only an affirmative user instruction may authorize a write.
    if re.search(r"\b(jangan|tanpa|do\s+not|don't|without)\b.{0,90}\b(apply|implement|repair|fix|lakukan|terapkan|perbaiki|lanjutkan)\b", utterance, re.I):
        return False
    # Negating the symptom ("tidak jalan, perbaiki") is not a prohibition.
    # Keep negation tied to the repair verb rather than any preceding symptom.
    if re.search(r"\b(tidak|belum|not)\s+(?:(?:usah|perlu|boleh|ingin|mau|akan|siap|setuju|ready|to|yet|untuk|saya|kamu|anda)\s+){0,4}(apply|implement|repair|fix|lakukan|terapkan|perbaiki|lanjutkan)\b", utterance, re.I):
        return False
    if re.search(r"\b(before|sebelum)\b.{0,90}\b(approve|setuju|menyetujui|persetujuan)\b", utterance, re.I):
        return False
    return bool(_REPAIR_APPLY_RE.search(utterance))

def has_explicit_high_risk_approval(text: str) -> bool:
    return bool(_HIGH_RISK_APPROVAL_RE.search(text or ""))
