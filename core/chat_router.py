"""Explicit text-only router for configured providers; Gemini Live stays separate.

This is not a tool-calling or multimodal router. Never silently fall back to
another provider or send prompts to Gemini when a non-Gemini provider is chosen.
"""
from __future__ import annotations

from core.setup_config import load_config
from core.llm_trace import traced_text_call
from core.llm_compatible import ENDPOINTS, generate_text
from core.llm_anthropic import generate_text as generate_claude_text
from core.llm_codex import generate_text as generate_codex_text

def generate_chat_text(prompt: str, *, config: dict | None = None, timeout: float | None = None) -> str:
    """Route a plain text request to the explicitly configured provider."""
    settings = load_config() if config is None else config
    provider = str(settings.get("llm_provider") or "gemini").strip().lower()
    if provider == "gemini":
        from core.gemini import text, SMART
        return traced_text_call(provider, "configured_gemini_text_ladder", lambda: text(prompt, tier=SMART))
    if provider not in ENDPOINTS and provider not in {"anthropic", "openai_codex", "google_oauth"}:
        raise ValueError(f"Chat provider {provider!r} is not implemented")
    models = str((settings.get("provider_models") or {}).get(provider)
                 or settings.get("chat_models") or settings.get("text_models") or "")
    model = next((x.strip() for x in models.split(",") if x.strip()), "")
    if not model:
        raise ValueError(f"Configure a text model for {provider}")
    if provider == "google_oauth":
        from core.llm_google_oauth import generate_text as generate_google_oauth
        return traced_text_call(provider, model, lambda: generate_google_oauth(model, prompt, timeout=timeout if timeout is not None else 30.0))
    if provider == "openai_codex":
        return traced_text_call(provider, model, lambda: generate_codex_text(model, prompt, timeout=timeout if timeout is not None else 120.0))
    key = str(settings.get(f"{provider}_api_key") or "")
    options = {"api_key": key}
    if timeout is not None:
        options["timeout"] = timeout
    if provider == "anthropic":
        return traced_text_call(provider, model, lambda: generate_claude_text(model, prompt, **options))
    return traced_text_call(provider, model, lambda: generate_text(provider, model, prompt, **options))
