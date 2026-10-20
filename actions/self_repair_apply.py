"""Transactional, policy-guarded application of a reviewed self-repair plan."""
from __future__ import annotations

import ast
import json
import threading
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
    "actions/", "core/", "plugins/", "dashboard/static/",
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


def _load_plan(plan_id: str) -> dict:
    if not plan_id or not plan_id.replace("-", "").isalnum():
        return {}
    path = BASE_DIR / "storage" / "self_repair" / "plans" / f"{plan_id}.json"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return obj if isinstance(obj, dict) and obj.get("plan_id") == plan_id else {}

def _result(message, *, status="FAILED", **fields):
    return json.dumps({"ok": status != "FAILED", "status": status,
        "verified": status == "SUCCESS", "message": message, **fields}, ensure_ascii=False)


_REPAIR_LOCK = threading.Lock()


def self_repair_apply(parameters: dict, **_kwargs) -> str:
    if not _REPAIR_LOCK.acquire(blocking=False):
        return _result("Another repair transaction is running; no second repair was started.", status="WAITING")
    try:
        return _apply_repair(parameters)
    finally:
        _REPAIR_LOCK.release()


def _apply_repair(parameters: dict) -> str:
    params = dict(parameters or {})
    plan_id = str(params.get("plan_id", "")).strip()
    if plan_id:
        plan = _load_plan(plan_id)
        if not plan:
            return _result("Repair rejected: the diagnostic repair plan is missing or invalid. Run diagnosis again.")
        # The persisted plan is the source of edit authority. Model-generated
        # operations cannot override it.
        for key in ("problem", "root_cause", "confidence", "risk", "operations"):
            if key in plan:
                params[key] = plan[key]
    try:
        recover_incomplete_transactions()
    except (RepairPolicyError, OSError, UnicodeError) as exc:
        return _result('Repair blocked: an earlier transaction could not be recovered. Inspect its snapshot and audit log before starting another repair.',
                       failure_stage='recover_previous_transaction', error_type=type(exc).__name__)
    try:
        attempt = int(params.get("attempt", 1))
    except (TypeError, ValueError):
        return _result("Repair rejected: attempt must be an integer.")
    if attempt < 1 or attempt > MAX_ATTEMPTS:
        return _result(f"Repair rejected: autonomous repair attempt budget is {MAX_ATTEMPTS}. Roll back and report to the user.")
    if params.get("apply") is not True or params.get("authorization") != "APPLY_DIAGNOSTIC_REPAIR":
        return _result("Repair rejected: explicit APPLY_DIAGNOSTIC_REPAIR authorization is required.")
    if str(params.get("confidence", "")).lower() != "high":
        return _result("Repair rejected: only high-confidence diagnoses may be applied.")
    operations = params.get("operations")
    if not isinstance(operations, list) or not operations:
        return _result("Repair rejected: provide at least one exact operation.")

    prepared = []
    originals = {}
    candidates = {}
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
            if rel not in originals:
                originals[rel] = path.read_text(encoding="utf-8")
            current = candidates.get(rel, originals[rel])
            if current.count(old) != 1:
                raise RepairPolicyError(f"expected exactly one match in {rel}")
            candidate = current.replace(old, new, 1)
            candidates[rel] = candidate
            total += len(new)

        prepared = list(candidates.items())
        for rel, candidate in prepared:
            _validate_candidate(rel, candidate)
        requested_risk = str(params.get("risk", "medium")).lower()
        risk = classify_risk(requested_risk, [x[0] for x in prepared], [x[1] for x in prepared])
        high_approval = params.get("high_risk_approval") == "HIGH_RISK_REPAIR_APPROVED"
        enforce_policy([x[0] for x in prepared], total, risk, high_approval)
    except (RepairPolicyError, SyntaxError, ElementTree.ParseError, OSError, UnicodeError) as exc:
        audit("repair_rejected", reason=str(exc))
        return _result(f"Repair rejected by Repair Guard: {exc}")

    validation_plan = ["candidate syntax/XML validation", "sandbox import/compile/full tests", "post-write import/compile/full tests"]
    try:
        txid = begin_transaction(str(params.get("problem", "diagnostic repair")), risk, originals, validation_plan)
    except (OSError, UnicodeError) as exc:
        return _result("Repair snapshot could not be prepared; production source was not modified.",
                       source_modified=False, failure_stage="prepare_snapshot", error_type=type(exc).__name__)
    candidates = dict(prepared)
    sandbox_ok, sandbox_results = validate_sandbox(candidates)
    if not sandbox_ok:
        try:
            set_status(txid, "REJECTED_SANDBOX", validation=sandbox_results)
        except (OSError, UnicodeError) as exc:
            return _result("Repair validation failed and its status could not be persisted; inspect the transaction snapshot. Production source was not modified.",
                transaction_id=txid, source_modified=False, failure_stage="persist_validation_failure",
                error_type=type(exc).__name__, validation=sandbox_results)
        _record_failure({"problem": str(params.get("problem", "")), "hypothesis": str(params.get("root_cause", "")), "files_changed": [], "test_result": sandbox_results, "failure_reason": "sandbox validation failed before production write", "rollback": [], "confidence": "EXPERIMENTAL", "validation_status": "failed"})
        return _result(f"Repair candidate failed sandbox validation; production files were not modified. Transaction: {txid}.", transaction_id=txid, validation=sandbox_results, source_modified=False)
    for rel, original in originals.items():
        try:
            unchanged = (BASE_DIR / rel).read_text(encoding="utf-8") == original
        except (OSError, UnicodeError):
            unchanged = False
        if not unchanged:
            set_status(txid, "REJECTED_STALE", changed_files=[])
            return _result("Repair source changed during sandbox validation. No production write or rollback was performed; inspect the current source before a new diagnosis.", transaction_id=txid)
    try:
        # Persist write intent before the first edit so crash recovery knows
        # when restoring snapshots is necessary.
        set_status(txid, "CANDIDATE_WRITTEN", changed_files=[x[0] for x in prepared])
        for rel, candidate in prepared:
            write_candidate(rel, candidate)
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
            return _result(f"Repair candidate failed validation and was rolled back completely. Transaction: {txid}.", transaction_id=txid, validation=results, rolled_back=True)
        set_status(txid, "ACCEPTED", validation=results)
        record_knowledge("fixes", {
            "problem": str(params.get("problem", "")), "root_cause": str(params.get("root_cause", "")),
            "affected_component": [x[0] for x in prepared], "successful_fix": "exact reviewed replacements",
            "validation": results, "regression_risk": risk, "source": "self_repair_transaction",
            "project_commit": str(params.get("project_commit", "unknown")),
            "environment": str(params.get("environment", "unknown")),
            "confidence": "CONFIRMED", "validation_status": "verified",
        })
        files = [rel for rel, _ in prepared]
        restart_required = any(rel.endswith(".py") for rel in files)
        rebuild_required = any(rel.startswith("android-companion/") for rel in files)
        activation = "rebuild_android" if rebuild_required else "restart_server" if restart_required else "reload_changed_resource"
        return _result("Guarded repair accepted after source validation. Runtime behavior has not yet been verified.",
            status="WAITING", source_verified=True, transaction_id=txid, files_changed=files,
            validation=results, activation_required=activation, restart_required=restart_required,
            rebuild_required=rebuild_required, runtime_verified=False,
            instruction="Do not repeat the patch or claim the symptom is fixed. "
                "For server Python changes restart with python main.py --restart; for Android changes rebuild/install the APK. "
                "Then reproduce the original action and verify its actual result. Never restart automatically inside this tool.")
    except Exception as exc:
        try:
            restored = rollback(txid)
        except Exception as rollback_exc:
            audit("rollback_failed", transaction=txid, error=repr(rollback_exc))
            return _result(f"Repair failed; automatic rollback also failed. Transaction {txid} requires manual recovery from its snapshot.")
        _record_failure({"problem": str(params.get("problem", "")), "failure_reason": repr(exc), "rollback": restored, "confidence": "EXPERIMENTAL", "validation_status": "failed"})
        return _result(f"Repair failed and was rolled back completely. Transaction: {txid}.")


TOOL = {
    "name": "self_repair_apply",
    "description": (
        "Apply an explicitly authorized, high-confidence diagnostic repair as a guarded transaction. "
        "The engine enforces path/change budgets, protected safety areas, risk approval, snapshots, fixed validation, "
        "full rollback on failure, redacted audit logging, and verified/failure knowledge. It never installs dependencies, "
        "runs model-supplied shell commands, restarts services, changes privileges, commits, or pushes."
    ),
    "parameters": {"type": "OBJECT", "properties": {
         "plan_id": {"type": "STRING", "description": "Server-side plan id returned by self_repair_diagnostic"},
        "apply": {"type": "BOOLEAN"}, "authorization": {"type": "STRING"},
        "confidence": {"type": "STRING"}, "risk": {"type": "STRING"},
        "high_risk_approval": {"type": "STRING"}, "problem": {"type": "STRING"},
        "root_cause": {"type": "STRING"}, "project_commit": {"type": "STRING"},
        "environment": {"type": "STRING"}, "attempt": {"type": "INTEGER"},
        "operations": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "file": {"type": "STRING"}, "old": {"type": "STRING"}, "new": {"type": "STRING"}},
            "required": ["file", "old", "new"]}},
    }, "required": ["apply", "authorization"]},
    "handler": self_repair_apply,
}
