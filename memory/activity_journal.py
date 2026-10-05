"""Durable, local activity memory for conversation and completed work.

This journal survives server restarts.  It is intentionally separate from personal
long-term facts: conversation/activity history is append-only evidence, not a fact
that should silently overwrite a user preference.
"""
from __future__ import annotations
import json, os, re, threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "storage" / "activity" / "journal.jsonl"
_LOCK = threading.RLock()
MAX_RECORDS = 4000
MAX_TEXT = 6000

# Do not turn credentials spoken in conversation into durable memory.
_SECRET = re.compile(r"(?i)\b(password|passcode|pin|otp|one[- ]time password|kata sandi|kode otp)\b\s*[:=]?\s*\S+")

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _clean(text: str) -> str:
    text = " ".join(str(text or "").split())[:MAX_TEXT]
    return _SECRET.sub(lambda m: m.group(1) + " [REDACTED]", text)

def append(kind: str, text: str, **meta) -> None:
    text = _clean(text)
    if not text:
        return
    rec = {"ts": _now(), "kind": str(kind), "text": text}
    for k, v in meta.items():
        if v not in (None, "", [], {}):
            rec[str(k)] = v
    with _LOCK:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        _compact_if_needed()

def _read() -> list[dict]:
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict): out.append(item)
        except Exception:
            continue
    return out

def _compact_if_needed() -> None:
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    if len(lines) <= MAX_RECORDS + 250:
        return
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text("\n".join(lines[-MAX_RECORDS:]) + "\n", encoding="utf-8")
    os.replace(tmp, PATH)

def recent(limit: int = 12) -> list[dict]:
    return _read()[-max(1, int(limit)):]

def recent_context(limit: int = 12) -> str:
    rows = [r for r in recent(limit * 2) if r.get("kind") in {"user", "assistant", "task_completed"}]
    rows = rows[-limit:]
    if not rows:
        return ""
    lines = ["[RECENT DURABLE ACTIVITY — reference only; do not repeat or resume old requests unless the user asks]"]
    for r in rows:
        label = {"user":"User", "assistant":"JARVIS", "task_completed":"Completed work"}.get(r.get("kind"), r.get("kind"))
        lines.append(f"- {r.get('ts','')} {label}: {r.get('text','')}")
    return "\n".join(lines)

def search(query: str, limit: int = 8) -> list[dict]:
    words = [w for w in re.split(r"[^\w]+", str(query or "").casefold()) if len(w) > 1]
    scored = []
    for i, rec in enumerate(_read()):
        hay = " ".join(str(rec.get(k, "")) for k in ("kind", "text", "goal", "artifact", "filename", "destination")).casefold()
        score = sum(3 if w in str(rec.get("text", "")).casefold() else 1 for w in words if w in hay) if words else 1
        if score:
            scored.append((score, i, rec))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [r for _s, _i, r in scored[:max(1, int(limit))]]
