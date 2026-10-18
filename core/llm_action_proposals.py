"""Validate Text LLM action proposals before any Mark tool executor sees them.

This module deliberately never executes actions or accepts model-authored approval.
"""
from __future__ import annotations

import json
import re


def validate_proposal(raw: str, allowed_tools: set[str]) -> dict:
    if not isinstance(raw, str) or len(raw) > 32000:
        raise ValueError("Invalid proposal response")
    raw = raw.strip()
    if raw.startswith("```"):
        fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL | re.IGNORECASE)
        if not fenced:
            raise ValueError("Proposal must be a single JSON object")
        raw = fenced.group(1).strip()
    try:
        proposal = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("Proposal must be valid JSON") from exc
    if not isinstance(proposal, dict) or set(proposal) != {"tool", "args", "reason"}:
        raise ValueError("Proposal must contain only tool, args and reason")
    tool, args, reason = proposal["tool"], proposal["args"], proposal["reason"]
    if not isinstance(tool, str) or tool not in allowed_tools:
        raise ValueError("Tool is not in the available tool registry")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError("Invalid reason")
    if not isinstance(args, dict) or len(args) > 30:
        raise ValueError("Invalid tool arguments")
    if any(not isinstance(key, str) or not key or len(key) > 100 for key in args):
        raise ValueError("Invalid argument key")
    if len(json.dumps(args, ensure_ascii=False)) > 12000:
        raise ValueError("Tool arguments are too large")
    return {"tool": tool, "args": args, "reason": reason, "executed": False}


def propose_action(task: str, declarations: list[dict], *, config: dict | None = None) -> dict:
    """Request exactly one action proposal from the configured Text LLM.

    Registry tool schemas guide arguments; this does not authorize execution.
    """
    from core.llm_text import generate
    if not isinstance(task, str) or not task.strip() or len(task) > 12000:
        raise ValueError("Invalid task")
    names = sorted({
        d["name"] for d in declarations
        if isinstance(d, dict) and isinstance(d.get("name"), str)
        and d["name"] not in {"delegate_to_text_llm", "plan_with_text_llm", "propose_text_action", "task_continuity"}
    })
    if not names:
        raise ValueError("No available tools")
    schemas = [{key: declaration[key] for key in ("name", "description", "parameters")
                if key in declaration}
               for declaration in declarations
               if isinstance(declaration, dict) and declaration.get("name") in names]
    prompt = (
        "Propose exactly ONE next action for the user request. Return ONLY JSON "
        "with keys tool (one of the available names), args (object), reason (string). "
        "Do not invent approvals, permissions or results. Do not execute the action. "
        "Choose an operational step for the request, not bookkeeping or task tracking. "
        "For partial DOCX revisions use document_editor list/inspect/revise, not dev_agent. "
        "A filename in the request does not prove a source or revised file exists.\n"
        "Available tool schemas (follow required argument names and types): "
        + json.dumps(schemas, ensure_ascii=False) + "\n"
        "User request: " + task
    )
    return validate_proposal(generate(prompt, config=config), set(names))
