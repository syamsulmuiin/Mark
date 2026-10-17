"""Validate Text LLM action proposals before any Mark tool executor sees them.

This module deliberately never executes actions or accepts model-authored approval.
"""
from __future__ import annotations

import json


def validate_proposal(raw: str, allowed_tools: set[str]) -> dict:
    if not isinstance(raw, str) or len(raw) > 32000:
        raise ValueError("Invalid proposal response")
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

    Only the registry's tool names are exposed; this does not authorize execution.
    """
    from core.llm_text import generate
    if not isinstance(task, str) or not task.strip() or len(task) > 12000:
        raise ValueError("Invalid task")
    names = sorted({
        d["name"] for d in declarations
        if isinstance(d, dict) and isinstance(d.get("name"), str)
        and d["name"] not in {"delegate_to_text_llm", "plan_with_text_llm", "propose_text_action"}
    })
    if not names:
        raise ValueError("No available tools")
    prompt = (
        "Propose exactly ONE next action for the user request. Return ONLY JSON "
        "with keys tool (one of the available names), args (object), reason (string). "
        "Do not invent approvals, permissions or results. Do not execute the action.\n"
        "Available tools: " + json.dumps(names) + "\n"
        "User request: " + task
    )
    return validate_proposal(generate(prompt, config=config), set(names))
