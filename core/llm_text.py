"""Single entry point for text LLM requests.

Plain text is provider-aware. Structured output, tool calling and multimodal
must be added as explicit capabilities; never silently send them to Gemini.
"""
from __future__ import annotations
from core.chat_router import generate_chat_text


def generate(prompt: str, *, config: dict | None = None, timeout: float | None = None) -> str:
    """Generate plain text with the configured chat provider."""
    if timeout is not None:
        return generate_chat_text(prompt, config=config, timeout=timeout)
    return generate_chat_text(prompt, config=config)


def plan(task: str, *, config: dict | None = None) -> dict:
    """Ask the configured Text LLM for a bounded plan; never execute it.

    Treat model output as untrusted data. Only a human-readable plan is
    returned; actions must still pass through Mark's existing tool safeguards.
    """
    import json
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Task is required")
    if len(task) > 12_000:
        raise ValueError("Task is too long")
    prompt = (
        "Create a concise action plan for the following user request. "
        "Return ONLY a JSON object with keys summary (string) and steps "
        "(array of 1 to 8 strings). Do not claim actions were performed, "
        "do not include secrets, and do not execute anything.\n"
        "User request:\n" + task
    )
    raw = generate(prompt, config=config)
    if len(raw) > 32_000:
        raise ValueError("Text LLM plan response is too long")
    try:
        result = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError("Text LLM did not return valid JSON") from exc
    if not isinstance(result, dict) or set(result) != {"summary", "steps"}:
        raise ValueError("Text LLM plan must contain summary and steps")
    summary, steps = result["summary"], result["steps"]
    if (not isinstance(summary, str) or not summary.strip()
            or len(summary) > 2000 or not isinstance(steps, list)
            or not 1 <= len(steps) <= 8
            or any(not isinstance(step, str) or not step.strip()
                   or len(step) > 1000 for step in steps)):
        raise ValueError("Text LLM returned an invalid plan")
    return {"summary": summary, "steps": steps, "executed": False}
