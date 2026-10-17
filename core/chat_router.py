"""Explicit text-only router for configured providers; Gemini Live stays separate.

This is not a tool-calling or multimodal router. Never silently fall back to
another provider or send prompts to Gemini when a non-Gemini provider is chosen.
"""
from __future__ import annotations

from core.setup_config import load_config
from core.llm_compatible import ENDPOINTS, generate_text

def generate_chat_text(prompt: str, *, config: dict | None = None) -> str:
    """Route a plain text request to the explicitly configured provider."""
    settings = load_config() if config is None else config
    provider = str(settings.get("llm_provider") or "gemini").strip().lower()
    if provider == "gemini":
        from core.gemini import text, SMART
        return text(prompt, tier=SMART)
    if provider not in ENDPOINTS:
        raise ValueError(f"Chat provider {provider!r} is not implemented")
    models = str(settings.get("text_models") or "")
    model = next((x.strip() for x in models.split(",") if x.strip()), "")
    if not model:
        raise ValueError(f"Configure a text model for {provider}")
    key = str(settings.get(f"{provider}_api_key") or "")
    return generate_text(provider, model, prompt, api_key=key)
