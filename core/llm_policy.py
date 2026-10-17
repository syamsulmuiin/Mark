"""Provider-aware policy for separating voice conversation and text reasoning."""
from __future__ import annotations

from core.setup_config import load_config


def live_delegation_instruction(config: dict | None = None) -> str:
    """Tell the Live voice model when to use the independent Text LLM.

    Instructions guide behavior but do not guarantee tool invocation.
    """
    settings = load_config() if config is None else config
    provider = str(settings.get("llm_provider") or "gemini").strip().lower()
    if provider == "gemini":
        return ""
    return (
        "[TEXT LLM DELEGATION POLICY]\n"
        f"The configured reasoning provider is {provider}, not Gemini Live. "
        "You are the real-time voice interface. For substantive questions, "
        "analysis, multi-step planning, troubleshooting and decisions, call "
        "delegate_to_text_llm with the user's complete request and relevant context "
        "before answering. Speak the returned answer faithfully; do not invent a "
        "different answer. You may directly handle brief greetings, acknowledgements "
        "and turn-taking. For actions, existing tool execution remains available; "
        "do not claim that delegate_to_text_llm executes actions. If delegation "
        "fails, explain the failure rather than silently answering with Gemini.\n"
    )
