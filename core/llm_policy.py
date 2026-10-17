"""Provider-aware policy for separating voice conversation and text reasoning."""
from __future__ import annotations

from core.setup_config import load_config


def live_delegation_instruction(config: dict | None = None) -> str:
    """Tell the Live voice model when to use the independent Text LLM.

    Instructions guide behavior but do not guarantee tool invocation.
    """
    settings = load_config() if config is None else config
    provider = str(settings.get("llm_provider") or "gemini").strip().lower()
    if provider == "gemini" and settings.get("live_provider", "gemini") == "gemini":
        return ""
    voice = "OpenAI Realtime" if settings.get("live_provider") == "openai_realtime" else "Gemini Live"
    return (
        "[TEXT LLM DELEGATION POLICY]\n"
        f"The configured reasoning provider is {provider}. The voice transport is {voice}. "
        "You are the real-time voice interface. For substantive questions, "
        "analysis, troubleshooting and decisions, call "
        "delegate_to_text_llm with the user's complete request and relevant context "
        "before answering. For multi-step activities, first call plan_with_text_llm "
        "to obtain a proposed plan; that plan is NOT executed. When a tool "
        "action is needed, call propose_text_action to let the Text LLM select "
        "a proposed tool and arguments. That proposal must be confirmed "
        "through the Mark approval gate; NEVER call the underlying action tool "
        "directly or bypass propose_text_action when the configured Text "
        "provider is not Gemini. If approval is unavailable, report the "
        "failure and do not perform the action. Speak the returned "
        "answer faithfully; do not invent a "
        "different answer. You may directly handle brief greetings, acknowledgements "
        "and turn-taking. For actions, only the confirmed proposal path is allowed; "
        "do not claim that delegate_to_text_llm executes actions. If delegation "
        "fails, explain the failure rather than silently answering with Gemini.\n"
    )
