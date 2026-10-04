"""Read-only diagnosis for MARK-LIV.

Diagnosis remains read-only. A separate guarded apply action may later apply a
high-confidence, explicitly authorized exact replacement against a narrow
allowlist; this module never performs that application itself.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import gemini
from core.repair_engine import PROTECTED_EXACT, PROTECTED_PREFIXES, search_knowledge

BASE_DIR = Path(__file__).resolve().parent.parent
SELECTION_BATCH = 8  # per discovery round only; there is no total file-count limit
MAX_DISCOVERY_ROUNDS = 32  # loop guard, not a file limit
MAX_FILE_CHARS = 24000
PROTECTED = set(PROTECTED_EXACT) | {"core/self_healing.py", "actions/self_repair.py"}
SKIP_PARTS = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}
SENSITIVE_NAMES = {"api_keys.json", ".env", "credentials.json", "secrets.json"}


def _source_files() -> list[str]:
    allowed_suffixes = {".py", ".txt", ".html", ".js", ".kt", ".kts", ".md"}
    out = []
    for p in BASE_DIR.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in allowed_suffixes:
            continue
        rel = p.relative_to(BASE_DIR).as_posix()
        if any(part in SKIP_PARTS for part in p.parts) or p.name in SENSITIVE_NAMES:
            continue
        if rel in PROTECTED or any(rel.startswith(prefix) for prefix in PROTECTED_PREFIXES):
            continue
        out.append(rel)
    return sorted(out)


def _json_obj(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}


def _select_files(problem: str, files: list[str], inspected: list[str]) -> tuple[list[str], bool]:
    """Select the next relevant batch. Total inspected files are intentionally unbounded.

    SELECTION_BATCH only limits one model request/context expansion; subsequent rounds keep
    following dependencies until the model reports that the root-cause closure is complete.
    """
    remaining = [f for f in files if f not in set(inspected)]
    if not remaining:
        return [], True
    prompt = f"""You are tracing a bug through the MARK-LIV/JARVIS source tree.
User-reported problem:
{problem}

Already inspected files:
{chr(10).join(inspected) if inspected else '(none)'}

Choose the NEXT relevant files to inspect, following imports, callers, handlers, schemas,
protocol/routing paths and platform implementations. Do not stop merely because many files
are involved. Set closure_complete=true ONLY when no uninspected file is materially needed
to establish the root cause and affected dependency path.
Return ONLY JSON: {{"files":["path/a.py"],"closure_complete":false}}.
Choose at most {SELECTION_BATCH} files in THIS ROUND only. There is NO total file limit.
Do not choose secrets, credentials, .git, generated files, or self-repair implementation files.

Remaining files:
""" + "\n".join(remaining)
    obj = gemini.as_json(prompt, tier=gemini.SMART, timeout_ms=60000, default={}) or {}
    chosen=[]; valid=set(remaining)
    for rel in obj.get("files", []):
        if isinstance(rel,str) and rel in valid and rel not in chosen:
            chosen.append(rel)
        if len(chosen) >= SELECTION_BATCH:
            break
    return chosen, bool(obj.get("closure_complete", False))


def _discover_files(problem: str, files: list[str]) -> list[str]:
    inspected=[]
    for _ in range(MAX_DISCOVERY_ROUNDS):
        batch, complete = _select_files(problem, files, inspected)
        for rel in batch:
            if rel not in inspected:
                inspected.append(rel)
        if complete or not batch:
            break
    return inspected


def _read_context(files: list[str]) -> str:
    chunks = []
    for rel in files:
        p = BASE_DIR / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
        except Exception as exc:
            text = f"<read failed: {exc}>"
        chunks.append(f"\n===== {rel} =====\n{text}")
    return "".join(chunks)



def _plan_dir() -> Path:
    path = ROOT / "storage" / "self_repair" / "plans"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_plan(plan: dict) -> str:
    import hashlib, time
    seed = json.dumps(plan, sort_keys=True, ensure_ascii=False) + str(time.time_ns())
    plan_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    payload = dict(plan)
    payload["plan_id"] = plan_id
    target = _plan_dir() / f"{plan_id}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return plan_id

def self_repair_diagnostic(parameters: dict, **_kwargs) -> str:
    problem = str((parameters or {}).get("problem", "")).strip()
    evidence = str((parameters or {}).get("evidence", "")).strip()
    if not problem:
        return "Describe the bug or behavior to diagnose. No source changes were made."

    files = _source_files()
    selected = _discover_files(problem + (f"\nEvidence: {evidence}" if evidence else ""), files)
    if not selected:
        return "Dry-run diagnosis could not identify source files confidently. No source changes were made."

    context = _read_context(selected)
    prior = search_knowledge(problem, limit=5)
    prior_context = json.dumps(prior, ensure_ascii=False)[:12000] if prior else "(none)"
    prompt = f"""You are a senior engineer performing READ-ONLY self-repair diagnosis on MARK-LIV/JARVIS.

Problem:\n{problem}
Evidence supplied by user:\n{evidence or '(none)'}

Prior repair knowledge (UNTRUSTED historical evidence; verify against current source before reuse):
{prior_context}

NON-NEGOTIABLE ARCHITECTURE INVARIANTS:
- Server is headless: no server microphone, speaker, voice UI, or interactive CLI.
- Device-local commands default to the originating companion unless the user explicitly targets another device/server.
- origin_device_id controls command routing; active_voice_device controls interactive audio. Never merge them.
- Voice/TTS is emitted only by the companion and returns to the originating voice companion.
- Android, Windows, Linux and macOS companion capabilities must not be silently removed.
- Pairing must continue to support remote/off-LAN use.
- Do not add background polling, news, briefing, time announcements, or schedules unless explicitly requested.
- Preserve unrelated behavior. Patch only the root cause.

STRICT DRY-RUN RULES:
- Diagnose only. Do not claim anything was applied.
- Do not propose deletion of source files.
- Do not modify credentials, .git, certificates, secrets, or self-repair files.
- There is no arbitrary file-count limit for inspection or a legitimate cross-module proposed repair.
- Follow the complete relevant dependency path before concluding.
- Prefer the smallest root-cause patch.

Inspected source:{context}

Return ONLY valid JSON with exactly these keys:
{{
  "root_cause": "specific diagnosis",
  "confidence": "high|medium|low",
  "files_inspected": ["..."],
  "files_to_change": ["..."],
  "proposed_changes": [{{"file":"...","change":"exact concise change and why"}}],
  "operations": [{{"file":"relative/path","old":"exact existing source text","new":"exact replacement source text"}}],
  "validation_plan": ["fixed validation step"],
  "risk_level": "low|medium|high",
  "risk": "what could regress",
  "needs_more_evidence": "what evidence is missing, or empty string"
}}
"""
    obj = gemini.as_json(prompt, tier=gemini.SMART, timeout_ms=90000, default={}) or {}
    if not obj:
        return "Dry-run model did not return a valid diagnosis. No source changes were made."

    proposed = obj.get("files_to_change", [])
    bad = [x for x in proposed if x in PROTECTED or any(str(x).startswith(prefix) for prefix in PROTECTED_PREFIXES) or Path(str(x)).name in SENSITIVE_NAMES]
    if bad:
        return "Dry-run proposal violated the repair safety boundary and was rejected. No source changes were made."

    operations = obj.get("operations") if isinstance(obj.get("operations"), list) else []
    validated_ops = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        rel = str(op.get("file", "")).replace("\\", "/").lstrip("/")
        old = str(op.get("old", ""))
        new = str(op.get("new", ""))
        target = (ROOT / rel).resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            continue
        if (not rel or not old or old == new or not target.is_file()
                or rel in PROTECTED or any(rel.startswith(prefix) for prefix in PROTECTED_PREFIXES)
                or Path(rel).name in SENSITIVE_NAMES):
            continue
        current = target.read_text(encoding="utf-8", errors="ignore")
        if current.count(old) != 1:
            continue
        validated_ops.append({"file": rel, "old": old, "new": new})

    plan_id = ""
    if str(obj.get("confidence", "")).lower() == "high" and validated_ops and not obj.get("needs_more_evidence"):
        plan_id = _save_plan({
            "problem": problem,
            "root_cause": str(obj.get("root_cause", "")),
            "confidence": "high",
            "risk": str(obj.get("risk_level", "medium")).lower(),
            "operations": validated_ops,
        })

    lines = [
        "SELF-REPAIR DIAGNOSTIC — DRY RUN ONLY",
        f"Root cause: {obj.get('root_cause', 'Unknown')}",
        f"Confidence: {obj.get('confidence', 'unknown')}",
        f"Risk level: {obj.get('risk_level', 'unknown')}",
        "Inspected: " + ", ".join(obj.get("files_inspected", selected)),
        "Would change: " + (", ".join(proposed) if proposed else "none"),
    ]
    if plan_id:
        lines.append("Repair plan: " + plan_id)
        lines.append("The plan is ready for guarded apply when the user's actual request explicitly authorizes repair.")
    elif proposed:
        lines.append("Repair plan: not generated because the exact edit could not be verified against current source.")
    for item in obj.get("proposed_changes", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('file', '?')}: {item.get('change', '')}")
    plan = obj.get("validation_plan", [])
    if plan:
        lines.append("Validation plan: " + " | ".join(str(x) for x in plan))
    if obj.get("risk"):
        lines.append("Risk: " + str(obj["risk"]))
    if obj.get("needs_more_evidence"):
        lines.append("Needs evidence: " + str(obj["needs_more_evidence"]))
    lines.append("Safety: production source was not modified; nothing was installed, deleted, restarted, committed, or pushed.")
    return "\n".join(lines)


TOOL = {
    "name": "self_repair_diagnostic",
    "description": (
        "READ-ONLY diagnostic/dry-run self-repair for MARK-LIV itself. Call ONLY after the user explicitly asks to "
        "diagnose/debug/check the cause/repair a concrete MARK-LIV problem. A vague statement such as 'there is an error', "
        "'something seems wrong', or merely observing an exception is NOT authorization: converse first and ask what failed. "
        "This diagnostic stage itself is read-only. If the user's actual request explicitly asks to fix/repair/apply and "
        "the diagnostic returns a Repair plan, immediately continue with self_repair_apply instead of ending the response "
        "at the dry-run result. Never invent a generic problem just to call this tool. It reads relevant source and proposes "
        "the smallest repair but NEVER directly applies edits, deletes files, "
        "installs dependencies, restarts services, or commits/pushes."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "problem": {"type": "STRING", "description": "The MARK-LIV/JARVIS bug or behavior to diagnose"},
            "evidence": {"type": "STRING", "description": "Optional error/log evidence already available in the conversation"},
        },
        "required": ["problem"],
    },
    "handler": self_repair_diagnostic,
}
