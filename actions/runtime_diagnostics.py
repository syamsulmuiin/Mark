"""Bounded, read-only access to Mark server runtime diagnostics."""
from __future__ import annotations

import re
import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = BASE_DIR / "runtime"
_MAX_LINES = 200
_MAX_BYTES = 96 * 1024
_MAX_CHARS = 24_000
_MAX_INTERACTION_SCAN = 2 * 1024 * 1024

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


def _tail(path: Path, lines: int, *, interaction: bool = False, reads=None) -> str:
    try:
        if not path.is_file():
            if reads is not None:
                reads.append({"source": path.name, "state": "missing"})
            return ""
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            limit = _MAX_INTERACTION_SCAN if interaction else _MAX_BYTES
            fh.seek(max(0, size - limit))
            raw = fh.read(limit)
        if reads is not None:
            reads.append({"source": path.name, "state": "read", "bytes_read": len(raw)})
        text = raw.decode("utf-8", errors="replace")
        if size > limit and "\n" in text:
            text = text.split("\n", 1)[1]
        rows = text.splitlines()
        if interaction:
            noise = {"audio_in", "audio_out", "audio_to_gemini", "activity_start",
                     "activity_end", "barge_semantic_decision"}
            relevant = []
            for row in rows:
                try:
                    event = json.loads(row).get("event")
                except (ValueError, AttributeError):
                    event = None
                if event not in noise:
                    relevant.append(row)
            rows = relevant
        selected = rows[-max(1, min(int(lines), _MAX_LINES)):]
        bounded = "\n".join(selected)
        if len(bounded) > _MAX_CHARS:
            bounded = bounded[-_MAX_CHARS:]
            if "\n" in bounded:
                bounded = bounded.split("\n", 1)[1]
        return _redact(bounded).strip()
    except Exception as exc:
        if reads is not None:
            reads.append({"source": path.name, "state": "failed", "error_type": type(exc).__name__})
        return f"<read failed: {type(exc).__name__}>"


def _metadata(path: Path) -> str:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        return f"File modified (UTC): {modified}; entries may include older runs."
    except OSError:
        return "File timestamp unavailable."


def _log_state(path: Path) -> str:
    try:
        size = path.stat().st_size
        return f"{path.name}: present, {size} bytes; " + _metadata(path)
    except FileNotFoundError:
        return f"{path.name}: missing (no file at the server runtime path)."
    except OSError as exc:
        return f"{path.name}: inaccessible ({type(exc).__name__})."


def collect_runtime_evidence(scope: str = "all", lines: int = 120, *, reads=None) -> str:
    """Return bounded server diagnostics from fixed runtime paths only.

    No caller-supplied filesystem path is accepted. Rotated error logs are read
    only when the current error log is absent/empty, keeping the evidence small
    while still making startup failures recoverable after rotation.
    """
    scope = str(scope or "all").strip().lower()
    if scope not in {"all", "error", "interaction"}:
        scope = "all"
    lines = max(1, min(int(lines or 120), _MAX_LINES))
    chunks: list[str] = ["Server log availability (not companion-local logs):"]
    if scope in {"all", "error"}:
        chunks.append(_log_state(RUNTIME_DIR / "error.log"))
    if scope in {"all", "interaction"}:
        chunks.append(_log_state(RUNTIME_DIR / "interaction.log"))

    if scope in {"all", "error"}:
        current = _tail(RUNTIME_DIR / "error.log", lines, reads=reads)
        if current:
            chunks.append("===== runtime/error.log =====\n" + _metadata(RUNTIME_DIR / "error.log") + "\n" + current)
        else:
            for idx in range(1, 6):
                rotated = _tail(RUNTIME_DIR / f"error.log.{idx}", lines, reads=reads)
                if rotated:
                    chunks.append(f"===== runtime/error.log.{idx} =====\n" + rotated)
                    break

    if scope in {"all", "interaction"}:
        interaction = _tail(RUNTIME_DIR / "interaction.log", lines, interaction=True, reads=reads)
        if interaction:
            chunks.append("===== runtime/interaction.log (relevant events; audio/VAD omitted) =====\n" + _metadata(RUNTIME_DIR / "interaction.log") + "\n" + interaction)
        else:
            chunks.append("No relevant interaction events returned from the bounded scan; see file availability above.")

    # Inspection is not delivery. Expose only existing fixed log sources so
    # the model can continue an explicit file request without inventing paths.
    sources = []
    names = (["error.log"] if scope == "error" else
             ["interaction.log"] if scope == "interaction" else
             ["error.log", "interaction.log"])
    for name in names:
        path = RUNTIME_DIR / name
        try:
            if path.is_symlink() or not path.is_file():
                continue
            sources.append({"source": str(path.resolve()), "destination_name": name})
        except OSError:
            continue
    chunks.append("Log attachment sources (JSON):\n" + json.dumps(sources) + "\n"
                  "Reading diagnostics has not sent any file. If the user requested log files, "
                  "call send_server_file once per requested source above, with destination_device=current "
                  "and save_direct=false. Use these actual files, not copied diagnostic text or a renamed script. "
                  "Do not claim delivery until the transfer result confirms it. Raw log attachments are "
                  "not the redacted diagnostic excerpt. Existing file authorization still applies.")

    chunks.append("Error logs contain failures/warnings, not normal chat. An empty error log does not prove absence of failures. "
                  "Interaction entries are event metadata, not a full conversation transcript. "
                  "Interaction reads scan at most 2 MiB from the tail; older events may be outside this window.")
    return "\n\n".join(chunks)


def runtime_diagnostics(parameters: dict, **_kwargs) -> str:
    params = parameters or {}
    reads = []
    report = collect_runtime_evidence(
        scope=str(params.get("scope", "all")),
        lines=int(params.get("lines", 120) or 120),
        reads=reads,
    )
    successful = [r for r in reads if r["state"] == "read"]
    failed = any(r["state"] == "failed" for r in reads)
    scope = str(params.get("scope", "all")).lower().strip()
    required = {"error", "interaction"} if scope not in {"error", "interaction"} else {scope}
    covered = {"error" if r["source"].startswith("error.log") else "interaction" for r in successful}
    verified = not failed and required <= covered
    return json.dumps({
        "status": "SUCCESS" if verified else "FAILED" if failed else "UNVERIFIED",
        "verified": verified,
        "reason": "log_collection_verified" if verified else "log_read_failed" if failed else "log_sources_missing",
        "verification_scope": "bounded_server_log_collection_only",
        "reads": reads, "report": report,
        "limitations": "Collection does not verify diagnosis, server health, repair, or attachment delivery.",
    })


TOOL = {
    "name": "runtime_diagnostics",
    "description": (
        "Read bounded, redacted Mark server runtime diagnostics from the fixed runtime/error.log "
        "and runtime/interaction.log locations. Use this when the user asks to inspect server errors, "
        "warnings, crashes, reconnect failures, conversation activity, model usage, missing logs, or why Mark failed. "
        "Call this tool before claiming logs are absent or empty. This action is read-only and cannot "
        "read arbitrary server files, credentials, configuration secrets, or companion-local logs. "
        "Inspection does not send files. For an explicit request to send logs, use the returned "
        "Log attachment sources with send_server_file to destination_device=current, save_direct=false."
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
