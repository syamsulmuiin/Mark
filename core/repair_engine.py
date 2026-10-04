"""Safety primitives for Mark self-repair.

This module is policy/transaction infrastructure, not a model-facing tool.  The
repair actions may call it, but autonomous repair is forbidden from modifying
this file or weakening its policy.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "storage" / "self_repair"
TX_DIR = STATE_DIR / "transactions"
KNOWLEDGE_DIR = STATE_DIR / "knowledge"
AUDIT_FILE = STATE_DIR / "audit.jsonl"
MAX_FILES = 8
MAX_DIFF_CHARS = 60000
MAX_ATTEMPTS = 3
VALIDATION_TIMEOUT = 120

# Immutable to the autonomous repair path. Human development may change these
# through the normal repository workflow, but the agent itself cannot.
PROTECTED_EXACT = {
    "core/repair_engine.py",
    "actions/self_repair_apply.py",
    "actions/self_repair_diagnostic.py",
    "core/action_loader.py",
    "core/plugin_loader.py",
    "core/confirm.py",
    "core/undo.py",
    "config/api_keys.json",
}
PROTECTED_PREFIXES = (
    ".git/", "config/certs/", "storage/self_repair/", ".github/workflows/",
)
SENSITIVE_RE = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|authorization)\s*[:=]\s*([^\s,;]+)")


class RepairPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class RepairPolicy:
    risk: str
    max_files: int = MAX_FILES
    max_diff_chars: int = MAX_DIFF_CHARS
    max_attempts: int = MAX_ATTEMPTS


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def redact(value: str) -> str:
    return SENSITIVE_RE.sub(lambda m: f"{m.group(1)}=<redacted>", str(value))


def audit(event: str, **fields) -> None:
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": int(time.time()), "event": event}
    for key, value in fields.items():
        if isinstance(value, str):
            record[key] = redact(value)
        else:
            record[key] = value
    with AUDIT_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_rel(rel: str) -> str:
    raw = str(rel or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or "\x00" in raw:
        raise RepairPolicyError("invalid repair path")
    p = Path(raw)
    if any(part in {"", ".", ".."} for part in p.parts):
        raise RepairPolicyError("path traversal is not allowed")
    normalized = p.as_posix()
    resolved = (BASE_DIR / normalized).resolve()
    try:
        resolved.relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise RepairPolicyError("repair path escapes repository") from exc
    return normalized


def is_protected(rel: str) -> bool:
    rel = normalize_rel(rel)
    return rel in PROTECTED_EXACT or any(rel.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def classify_risk(requested: str, files: Iterable[str], new_texts: Iterable[str]) -> str:
    requested = str(requested or "").lower().strip()
    if requested not in {"low", "medium", "high"}:
        raise RepairPolicyError("risk must be low, medium, or high")
    joined = "\n".join(files).lower() + "\n" + "\n".join(new_texts).lower()
    high_markers = ("auth", "credential", "permission", "privilege", "database migration", "subprocess", "os.system", "remote execution")
    medium_markers = ("network", "socket", "async", "thread", "database", "api", "routing")
    minimum = "high" if any(x in joined for x in high_markers) else "medium" if any(x in joined for x in medium_markers) else "low"
    order = {"low": 0, "medium": 1, "high": 2}
    return requested if order[requested] >= order[minimum] else minimum


def enforce_policy(files: list[str], replacement_chars: int, risk: str, high_risk_approval: bool) -> RepairPolicy:
    normalized = [normalize_rel(x) for x in files]
    if len(set(normalized)) != len(normalized):
        raise RepairPolicyError("duplicate repair file")
    if len(normalized) > MAX_FILES:
        raise RepairPolicyError(f"repair exceeds file budget ({MAX_FILES})")
    if replacement_chars > MAX_DIFF_CHARS:
        raise RepairPolicyError(f"repair exceeds change budget ({MAX_DIFF_CHARS} chars)")
    bad = [x for x in normalized if is_protected(x)]
    if bad:
        raise RepairPolicyError("protected safety area cannot be modified: " + ", ".join(bad))
    if risk == "high" and not high_risk_approval:
        raise RepairPolicyError("HIGH risk repair requires explicit HIGH_RISK_REPAIR_APPROVED approval")
    return RepairPolicy(risk=risk)


def begin_transaction(request: str, risk: str, originals: dict[str, str], validation_plan: list[str]) -> str:
    txid = f"{int(time.time())}-{uuid.uuid4().hex[:10]}"
    root = TX_DIR / txid
    (root / "snapshot").mkdir(parents=True, exist_ok=False)
    manifest = {
        "id": txid, "status": "PREPARED", "request": redact(request), "risk": risk,
        "created_at": int(time.time()), "validation_plan": validation_plan,
        "files": [], "attempt": 1,
    }
    for rel, text in originals.items():
        target = root / "snapshot" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        manifest["files"].append({"path": rel, "sha256": sha256_text(text)})
    _atomic_json(root / "manifest.json", manifest)
    audit("transaction_prepared", transaction=txid, risk=risk, files=list(originals), request=request)
    return txid


def _atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def set_status(txid: str, status: str, **extra) -> None:
    path = TX_DIR / txid / "manifest.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["status"] = status; obj.update(extra); obj["updated_at"] = int(time.time())
    _atomic_json(path, obj)
    audit("transaction_status", transaction=txid, status=status, **extra)


def rollback(txid: str) -> list[str]:
    root = TX_DIR / txid
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    restored = []
    for item in manifest["files"]:
        rel = normalize_rel(item["path"])
        snapshot = root / "snapshot" / rel
        text = snapshot.read_text(encoding="utf-8")
        _atomic_write(BASE_DIR / rel, text)
        restored.append(rel)
    set_status(txid, "ROLLED_BACK", restored=restored)
    return restored


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.repair-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def write_candidate(rel: str, text: str) -> None:
    _atomic_write(BASE_DIR / normalize_rel(rel), text)


def _run_validators(root: Path, changed_files: list[str], timeout: int) -> tuple[bool, list[dict]]:
    commands = [
        [sys.executable, "-c", "import core.repair_engine, actions.self_repair_apply, actions.self_repair_diagnostic"],
        [sys.executable, "-m", "compileall", "-q", "actions", "core", "dashboard", "main.py"],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    results = []
    for cmd in commands:
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout, env={**os.environ, "PYTHONPATH": str(root)})
            result = {"command": " ".join(cmd), "returncode": proc.returncode, "duration_ms": int((time.monotonic()-started)*1000), "output": redact((proc.stdout + proc.stderr)[-4000:])}
        except subprocess.TimeoutExpired:
            result = {"command": " ".join(cmd), "returncode": -1, "duration_ms": int((time.monotonic()-started)*1000), "output": "validation timeout"}
        results.append(result); audit("validation", files=changed_files, root=str(root), **result)
        if result["returncode"] != 0:
            return False, results
    return True, results


def validate_sandbox(candidates: dict[str, str], timeout: int = VALIDATION_TIMEOUT) -> tuple[bool, list[dict]]:
    """Validate a candidate in an isolated temporary repository copy first."""
    with tempfile.TemporaryDirectory(prefix="mark-repair-sandbox-") as td:
        root = Path(td) / "repo"
        shutil.copytree(BASE_DIR, root, ignore=shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", "storage", "build", "dist", ".pytest_cache"))
        for rel, text in candidates.items():
            target = root / normalize_rel(rel); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text, encoding="utf-8")
        return _run_validators(root, list(candidates), timeout)


def validate_repository(changed_files: list[str], timeout: int = VALIDATION_TIMEOUT) -> tuple[bool, list[dict]]:
    """Fixed post-write health validators; never executes model/user commands."""
    return _run_validators(BASE_DIR, changed_files, timeout)



def recover_incomplete_transactions() -> list[str]:
    """Rollback transactions interrupted before ACCEPTED/ROLLED_BACK.

    Called before a new repair. It never touches accepted transactions.
    """
    recovered = []
    if not TX_DIR.exists():
        return recovered
    for manifest_path in sorted(TX_DIR.glob("*/manifest.json")):
        try:
            obj = json.loads(manifest_path.read_text(encoding="utf-8"))
            if obj.get("status") not in {"PREPARED", "CANDIDATE_WRITTEN"}:
                continue
            txid = str(obj.get("id") or manifest_path.parent.name)
            rollback(txid)
            recovered.append(txid)
            audit("transaction_recovered_after_interruption", transaction=txid)
        except Exception as exc:
            audit("transaction_recovery_failed", transaction=manifest_path.parent.name, error=repr(exc))
    return recovered

def record_knowledge(kind: str, payload: dict) -> Path:
    if kind not in {"incidents", "fixes", "patterns", "failures", "environment", "architecture"}:
        raise RepairPolicyError("invalid knowledge category")
    root = KNOWLEDGE_DIR / kind
    root.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("timestamp", int(time.time()))
    payload.setdefault("confidence", "EXPERIMENTAL")
    payload.setdefault("validation_status", "candidate")
    path = root / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.json"
    _atomic_json(path, payload)
    audit("knowledge_recorded", kind=kind, path=str(path.relative_to(BASE_DIR)))
    return path


def search_knowledge(problem: str, limit: int = 5) -> list[dict]:
    terms = {x for x in re.findall(r"[a-z0-9_]{4,}", problem.lower())}
    scored = []
    if not KNOWLEDGE_DIR.exists():
        return []
    for path in KNOWLEDGE_DIR.rglob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = json.dumps(obj, ensure_ascii=False).lower()
        score = sum(1 for term in terms if term in text)
        if score:
            scored.append((score, path.stat().st_mtime, obj))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in scored[:limit]]
