"""Single entry point for text LLM requests.

Plain text is provider-aware. Structured output, tool calling and multimodal
must be added as explicit capabilities; never silently send them to Gemini.
"""
from __future__ import annotations
from core.chat_router import generate_chat_text


def generate(prompt: str, *, config: dict | None = None) -> str:
    """Generate plain text with the configured chat provider."""
    return generate_chat_text(prompt, config=config)
