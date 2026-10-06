"""Bounded, read-only access to Mark server runtime diagnostics."""
from __future__ import annotations

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = BASE_DIR / "runtime"
_MAX_LINES = 200
_MAX_BYTES = 96 * 1024
_MAX_CHARS = 24_000

_SECRET_PATTERNS = (
    re.compile(r"(?i)([\"']?\b(?:api[_-]?key|authorization|password|passcode|pin|otp|token|secret)\b[\"']?\s*[:=]\s*)[\"']?([^\s,;\"'}]+)"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"),
)


def _redact(text: str) -> str:
    out = str(text or "")
    for pattern in _SECRET_PATTERNS:
        if "(bearer)" in pattern.pattern.lower():
            out = pattern.sub("Bearer <redacted>", out)
        else:
            out = pattern.sub(lambda m: f"{m.group(1)}<redacted>", out)
    return out


def _tail(path: Path, lines: int) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - _MAX_BYTES))
            raw = fh.read(_MAX_BYTES)
        text = raw.decode("utf-8", errors="replace")
        if size > _MAX_BYTES and "\n" in text:
            text = text.split("\n", 1)[1]
        selected = text.splitlines()[-max(1, min(int(lines), _MAX_LINES)):]
        bounded = "\n".join(selected)
        if len(bounded) > _MAX_CHARS:
            bounded = bounded[-_MAX_CHARS:]
            if "\n" in bounded:
                bounded = bounded.split("\n", 1)[1]
        return _redact(bounded).strip()
    except Exception as exc:
        return f"<read failed: {type(exc).__name__}>"


def collect_runtime_evidence(scope: str = "all", lines: int = 120) -> str:
    """Return bounded server diagnostics from fixed runtime paths only.

    No caller-supplied filesystem path is accepted. Rotated error logs are read
    only when the current error log is absent/empty, keeping the evidence small
    while still making startup failures recoverable after rotation.
    """
    scope = str(scope or "all").strip().lower()
    if scope not in {"all", "error", "interaction"}:
        scope = "all"
    lines = max(1, min(int(lines or 120), _MAX_LINES))
    chunks: list[str] = []

    if scope in {"all", "error"}:
        current = _tail(RUNTIME_DIR / "error.log", lines)
        if current:
            chunks.append("===== runtime/error.log =====\n" + current)
        else:
            for idx in range(1, 6):
                rotated = _tail(RUNTIME_DIR / f"error.log.{idx}", lines)
                if rotated:
                    chunks.append(f"===== runtime/error.log.{idx} =====\n" + rotated)
                    break

    if scope in {"all", "interaction"}:
        interaction = _tail(RUNTIME_DIR / "interaction.log", lines)
        if interaction:
            chunks.append("===== runtime/interaction.log =====\n" + interaction)

    return "\n\n".join(chunks) if chunks else "No server runtime diagnostics are currently available."


def runtime_diagnostics(parameters: dict, **_kwargs) -> str:
    params = parameters or {}
    return collect_runtime_evidence(
        scope=str(params.get("scope", "all")),
        lines=int(params.get("lines", 120) or 120),
    )


TOOL = {
    "name": "runtime_diagnostics",
    "description": (
        "Read bounded, redacted Mark server runtime diagnostics from the fixed runtime/error.log "
        "and runtime/interaction.log locations. Use this when the user asks to inspect server errors, "
        "warnings, crashes, reconnect failures, or why Mark failed. This action is read-only and cannot "
        "read arbitrary server files, credentials, configuration secrets, or companion-local logs."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "scope": {"type": "STRING", "description": "all | error | interaction"},
            "lines": {"type": "INTEGER", "description": "Tail lines to read, capped at 200"},
        },
    },
    "handler": runtime_diagnostics,
}
