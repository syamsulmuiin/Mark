"""Provider-aware policy for separating voice conversation and text reasoning."""
from __future__ import annotations

from core.setup_config import load_config


def live_delegation_instruction(config: dict | None = None, *, live_model: str | None = None) -> str:
    """Tell the Live voice model when to use the independent Text LLM.

    Instructions guide behavior but do not guarantee tool invocation.
    """
    settings = load_config() if config is None else config
    provider = str(settings.get("llm_provider") or "gemini").strip().lower()
    voice = "OpenAI Realtime" if settings.get("live_provider") == "openai_realtime" else "Gemini Live"
    from core.llm_identity import identity_instruction
    return identity_instruction(settings, live_model=live_model) + (
        "[TEXT LLM DELEGATION POLICY]\n"
        f"The configured reasoning provider is {provider}. The voice transport is {voice}. "
        "You are the real-time voice interface. For substantive questions, "
        "analysis, troubleshooting and decisions, call "
        "delegate_to_text_llm with the user's complete request and relevant context "
        "before answering. For multi-step activities, first call plan_with_text_llm "
        "to obtain a proposed plan; that plan is NOT executed. When a tool "
        "action is needed, call propose_text_action to let the Text LLM select "
        "a proposed tool and arguments. The host decides whether confirmation is needed. "
        "Read-only diagnostics and simple reversible actions run immediately. Dangerous "
        "or unknown actions require a single confirmation; never request another approval "
        "for an action already pending or completed. Use runtime_diagnostics directly "
        "to inspect logs, and self_repair_diagnostic when the user requests diagnosis. "
        "When asked about interaction logs, errors, conversation activity or missing records, call runtime_diagnostics "
        "with scope=all before answering; do not delegate a log inspection to Text without the returned evidence. "
        "Distinguish missing, empty and unreadable files from no relevant events in the bounded scan. "
        "If the user already requested repair, continue a valid low/medium-risk plan "
        "through self_repair_apply; do not ask for the same permission again. "
        "Only ask the user to confirm when the tool returned approval_sent=true. "
        "When approval_sent=false, no popup exists: explain the returned failure or result. "
        "Speak the returned answer faithfully. Brief greetings and turn-taking may "
        "be handled directly. For ordinary device operations, existing tools remain available; "
        "do not claim that delegate_to_text_llm executes actions. If delegation "
        "fails, explain the failure rather than silently answering with Gemini. "
        "There is no implicit Text-to-Gemini fallback. Interruption audio is handled by the existing Live session, never an auxiliary "
        "classifier. Diagnose model usage from per-request traces, not guesses.\n"
    )
