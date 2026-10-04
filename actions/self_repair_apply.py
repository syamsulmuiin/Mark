"""Transactional, policy-guarded application of a reviewed self-repair plan."""
from __future__ import annotations

import ast
from pathlib import Path
from xml.etree import ElementTree

from core.repair_engine import (
    BASE_DIR, RepairPolicyError, audit, begin_transaction, classify_risk,
    enforce_policy, record_knowledge, recover_incomplete_transactions, rollback, set_status, validate_repository, validate_sandbox,
    write_candidate, MAX_ATTEMPTS,
)

MAX_REPLACEMENT_CHARS = 12000
ALLOWED_EXACT = {
    "main.py", "dashboard/server.py",
    "android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt",
    "android-companion/app/src/main/res/values/strings.xml",
    "SERVER_CLIENT_ARCHITECTURE.md", "readme.md",
}
ALLOWED_PREFIXES = (
    "actions/", "plugins/", "dashboard/static/",
    "desktop-companion/runtime/actions/",
    "android-companion/app/src/main/java/",
    "android-companion/app/src/main/res/drawable/",
    "android-companion/app/src/main/res/layout/",
)
ALLOWED_SUFFIXES = {".py", ".kt", ".kts", ".xml", ".js", ".html", ".md", ".txt"}
# Prefixes are constrained to source-like files; dependencies, deployment, secrets,
# repair policy and arbitrary filesystem paths are deliberately excluded.
#


def _allowed(rel: str) -> bool:
    return rel in ALLOWED_EXACT or (Path(rel).suffix.lower() in ALLOWED_SUFFIXES and any(rel.startswith(p) for p in ALLOWED_PREFIXES))


def _validate_candidate(rel: str, text: str) -> None:
    if rel.endswith(".py"):
        ast.parse(text, filename=rel)
    elif rel.endswith(".xml"):
        ElementTree.fromstring(text)



def _record_failure(payload: dict) -> None:
    try:
        record_knowledge("failures", payload)
    except Exception as exc:
        audit("failure_knowledge_write_failed", error=repr(exc))

def self_repair_apply(parameters: dict, **_kwargs) -> str:
    params = parameters or {}
    recover_incomplete_transactions()
    try:
        attempt = int(params.get("attempt", 1))
    except (TypeError, ValueError):
        return "Repair rejected: attempt must be an integer."
    if attempt < 1 or attempt > MAX_ATTEMPTS:
        return f"Repair rejected: autonomous repair attempt budget is {MAX_ATTEMPTS}. Roll back and report to the user."
    if params.get("apply") is not True or params.get("authorization") != "APPLY_DIAGNOSTIC_REPAIR":
        return "Repair rejected: explicit APPLY_DIAGNOSTIC_REPAIR authorization is required."
    if str(params.get("confidence", "")).lower() != "high":
        return "Repair rejected: only high-confidence diagnoses may be applied."
    operations = params.get("operations")
    if not isinstance(operations, list) or not operations:
        return "Repair rejected: provide at least one exact operation."

    prepared = []
    originals = {}
    total = 0
    try:
        for item in operations:
            if not isinstance(item, dict):
                raise RepairPolicyError("each operation must be an object")
            rel, old, new = str(item.get("file", "")), item.get("old"), item.get("new")
            if not _allowed(rel) or not isinstance(old, str) or not isinstance(new, str):
                raise RepairPolicyError(f"file or operation is outside the repair allowlist: {rel or '<missing>'}")
            if not old or old == new or len(new) > MAX_REPLACEMENT_CHARS:
                raise RepairPolicyError(f"invalid replacement for {rel}")
            path = BASE_DIR / rel
            if not path.is_file():
                raise RepairPolicyError(f"file does not exist: {rel}")
            current = path.read_text(encoding="utf-8", errors="replace")
            if current.count(old) != 1:
                raise RepairPolicyError(f"expected exactly one match in {rel}")
            candidate = current.replace(old, new, 1)
            _validate_candidate(rel, candidate)
            originals[rel] = current
            prepared.append((rel, candidate))
            total += len(new)

        requested_risk = str(params.get("risk", "medium")).lower()
        risk = classify_risk(requested_risk, [x[0] for x in prepared], [x[1] for x in prepared])
        high_approval = params.get("high_risk_approval") == "HIGH_RISK_REPAIR_APPROVED"
        enforce_policy([x[0] for x in prepared], total, risk, high_approval)
    except (RepairPolicyError, SyntaxError, ElementTree.ParseError) as exc:
        audit("repair_rejected", reason=str(exc))
        return f"Repair rejected by Repair Guard: {exc}"

    validation_plan = ["candidate syntax/XML validation", "sandbox import/compile/full tests", "post-write import/compile/full tests"]
    txid = begin_transaction(str(params.get("problem", "diagnostic repair")), risk, originals, validation_plan)
    candidates = dict(prepared)
    sandbox_ok, sandbox_results = validate_sandbox(candidates)
    if not sandbox_ok:
        set_status(txid, "REJECTED_SANDBOX", validation=sandbox_results)
        _record_failure({"problem": str(params.get("problem", "")), "hypothesis": str(params.get("root_cause", "")), "files_changed": [], "test_result": sandbox_results, "failure_reason": "sandbox validation failed before production write", "rollback": [], "confidence": "EXPERIMENTAL", "validation_status": "failed"})
        return f"Repair candidate failed sandbox validation; production files were not modified. Transaction: {txid}."
    try:
        for rel, candidate in prepared:
            write_candidate(rel, candidate)
        set_status(txid, "CANDIDATE_WRITTEN", changed_files=[x[0] for x in prepared])
        ok, results = validate_repository([x[0] for x in prepared])
        if not ok:
            restored = rollback(txid)
            _record_failure({
                "problem": str(params.get("problem", "")), "hypothesis": str(params.get("root_cause", "")),
                "files_changed": [x[0] for x in prepared], "test_result": results,
                "failure_reason": "post-write validation failed", "rollback": restored,
                "lesson": "Candidate was rejected; verify root cause and do not reuse this patch without new evidence.",
                "confidence": "EXPERIMENTAL", "validation_status": "failed",
            })
            return f"Repair candidate failed validation and was rolled back completely. Transaction: {txid}."
        set_status(txid, "ACCEPTED", validation=results)
        record_knowledge("fixes", {
            "problem": str(params.get("problem", "")), "root_cause": str(params.get("root_cause", "")),
            "affected_component": [x[0] for x in prepared], "successful_fix": "exact reviewed replacements",
            "validation": results, "regression_risk": risk, "source": "self_repair_transaction",
            "project_commit": str(params.get("project_commit", "unknown")),
            "environment": str(params.get("environment", "unknown")),
            "confidence": "CONFIRMED", "validation_status": "verified",
        })
        return f"Guarded repair accepted after validation. Transaction: {txid}. Files: " + ", ".join(x[0] for x in prepared) + ". No restart, install, commit, push, or privilege change was performed."
    except Exception as exc:
        try:
            restored = rollback(txid)
        except Exception as rollback_exc:
            audit("rollback_failed", transaction=txid, error=repr(rollback_exc))
            return f"Repair failed; automatic rollback also failed. Transaction {txid} requires manual recovery from its snapshot."
        _record_failure({"problem": str(params.get("problem", "")), "failure_reason": repr(exc), "rollback": restored, "confidence": "EXPERIMENTAL", "validation_status": "failed"})
        return f"Repair failed and was rolled back completely. Transaction: {txid}."


TOOL = {
    "name": "self_repair_apply",
    "description": (
        "Apply an explicitly authorized, high-confidence diagnostic repair as a guarded transaction. "
        "The engine enforces path/change budgets, protected safety areas, risk approval, snapshots, fixed validation, "
        "full rollback on failure, redacted audit logging, and verified/failure knowledge. It never installs dependencies, "
        "runs model-supplied shell commands, restarts services, changes privileges, commits, or pushes."
    ),
    "parameters": {"type": "OBJECT", "properties": {
        "apply": {"type": "BOOLEAN"}, "authorization": {"type": "STRING"},
        "confidence": {"type": "STRING"}, "risk": {"type": "STRING"},
        "high_risk_approval": {"type": "STRING"}, "problem": {"type": "STRING"},
        "root_cause": {"type": "STRING"}, "project_commit": {"type": "STRING"},
        "environment": {"type": "STRING"}, "attempt": {"type": "INTEGER"},
        "operations": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "file": {"type": "STRING"}, "old": {"type": "STRING"}, "new": {"type": "STRING"}},
            "required": ["file", "old", "new"]}},
    }, "required": ["apply", "authorization", "confidence", "risk", "problem", "operations"]},
    "handler": self_repair_apply,
}
