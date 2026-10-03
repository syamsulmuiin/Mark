"""Guarded application of an already-reviewed diagnostic repair plan.

This action is intentionally narrower than diagnosis. It accepts only exact
find/replace operations against an allowlisted set of runtime/companion files.
It never edits credentials, core/plugins, deployment files, systemd units, or
arbitrary paths; it never installs, restarts, commits, pushes, or builds.
"""
from __future__ import annotations

import ast
import os
import re
import tempfile
from pathlib import Path
from xml.etree import ElementTree

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIT_LOG = BASE_DIR / "runtime" / "repair_audit.log"
MAX_REPLACEMENT_CHARS = 12000
MAX_TOTAL_REPLACEMENT_CHARS = 60000

# These files remain immutable through the guarded repair path, even if the
# allowlist is expanded later. The repair mechanism must not repair itself.
PROTECTED_SELF_REPAIR = {
    "actions/self_repair_apply.py",
    "actions/self_repair_diagnostic.py",
    "core/self_healing.py",
}

ALLOWED_EXACT = {
    "main.py",
    "dashboard/server.py",
    "android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt",
    "android-companion/app/src/main/res/values/strings.xml",
    "PATCH_NOTES.md",
    "SERVER_CLIENT_ARCHITECTURE.md",
}
ALLOWED_PREFIXES = (
    "android-companion/app/src/main/res/drawable/",
    "android-companion/app/src/main/res/layout/",
)
FORBIDDEN_TERMS = (
    ".env", "credentials", "secret", "api_key", "token", "password",
    "systemctl", "subprocess", "os.system", "git push", "git commit",
)


def _allowed(rel: str) -> bool:
    return (
        rel not in PROTECTED_SELF_REPAIR
        and (rel in ALLOWED_EXACT or any(rel.startswith(p) and rel.endswith(".xml") for p in ALLOWED_PREFIXES))
    )


def _audit(message: str) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")


def _validate(rel: str, text: str) -> None:
    if rel.endswith(".py"):
        ast.parse(text, filename=rel)
    elif rel.endswith(".xml"):
        ElementTree.fromstring(text)


def _contains_forbidden(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in FORBIDDEN_TERMS)


def self_repair_apply(parameters: dict, **_kwargs) -> str:
    params = parameters or {}
    if params.get("apply") is not True or params.get("authorization") != "APPLY_DIAGNOSTIC_REPAIR":
        return "Repair rejected: explicit APPLY_DIAGNOSTIC_REPAIR authorization is required."
    if str(params.get("confidence", "")).lower() != "high":
        return "Repair rejected: only high-confidence diagnoses may be applied."

    operations = params.get("operations")
    if not isinstance(operations, list) or not operations:
        return "Repair rejected: provide at least one exact operation."

    prepared: list[tuple[Path, str, str, str]] = []
    seen: set[str] = set()
    total_replacement_chars = 0
    for item in operations:
        if not isinstance(item, dict):
            return "Repair rejected: each operation must be an object."
        rel = str(item.get("file", ""))
        old = item.get("old")
        new = item.get("new")
        if not _allowed(rel) or rel in seen or not isinstance(old, str) or not isinstance(new, str):
            return f"Repair rejected: file or operation is outside the allowlist: {rel or '<missing>'}."
        if not old or old == new or len(new) > MAX_REPLACEMENT_CHARS:
            return f"Repair rejected: invalid replacement for {rel}."
        total_replacement_chars += len(new)
        if total_replacement_chars > MAX_TOTAL_REPLACEMENT_CHARS:
            return "Repair rejected: total replacement size exceeds the safety budget."
        if _contains_forbidden(rel + "\n" + old + "\n" + new):
            return f"Repair rejected: sensitive or lifecycle content is not editable: {rel}."
        path = BASE_DIR / rel
        if not path.is_file():
            return f"Repair rejected: file does not exist: {rel}."
        current = path.read_text(encoding="utf-8", errors="replace")
        if current.count(old) != 1:
            return f"Repair rejected: expected exactly one match in {rel}."
        candidate = current.replace(old, new, 1)
        try:
            _validate(rel, candidate)
        except Exception as exc:
            return f"Repair rejected: validation failed for {rel}: {exc}"
        prepared.append((path, current, candidate, rel))
        seen.add(rel)

    changed: list[str] = []
    try:
        for path, _old, candidate, rel in prepared:
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.repair-", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(candidate)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            changed.append(rel)
    except Exception as exc:
        for path, old, _candidate, _rel in prepared:
            try:
                path.write_text(old, encoding="utf-8")
            except Exception:
                pass
        _audit(f"REJECTED rollback error={exc!r} files={changed}")
        return f"Repair failed and rollback was attempted: {exc}"

    _audit("APPLIED files=" + ",".join(changed))
    return (
        "Guarded diagnostic repair applied: " + ", ".join(changed) +
        ". No restart, build, install, commit, or push was performed."
    )


TOOL = {
    "name": "self_repair_apply",
    "description": (
        "Apply a high-confidence, explicitly authorized diagnostic repair using exact replacements only. "
        "Use only after self_repair_diagnostic has identified a concrete root cause and the user has authorized direct repair. "
        "The allowlist excludes credentials, core/plugins, deployment/system files, and arbitrary paths. "
        "Never use this to restart, install, build, commit, or push."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "apply": {"type": "BOOLEAN"},
            "authorization": {"type": "STRING"},
            "confidence": {"type": "STRING"},
            "operations": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "file": {"type": "STRING"},
                        "old": {"type": "STRING"},
                        "new": {"type": "STRING"},
                    },
                    "required": ["file", "old", "new"],
                },
            },
        },
        "required": ["apply", "authorization", "confidence", "operations"],
    },
    "handler": self_repair_apply,
}
