"""Provider-aware facade for text reasoning helpers, preserving Gemini SDK responses.

All helper reasoning uses the selected Text provider. Unsupported multimodal
input fails explicitly; it never falls back to Live or another provider.
"""
from __future__ import annotations
import json
from types import SimpleNamespace
from core import gemini
from core.setup_config import load_config
from core.llm_text import generate

FAST, SMART = gemini.FAST, gemini.SMART


def call(contents, tier=SMART, config=None, timeout_ms=30000):
    settings = load_config()
    if str(settings.get("llm_provider") or "gemini").strip().lower() == "gemini":
        from core.response_language import language_instruction
        policy = language_instruction(config=settings)
        if policy:
            config = dict(config or {})
            config["system_instruction"] = str(config.get("system_instruction") or "") + "\n" + policy
        return gemini.call(contents, tier=tier, config=config, timeout_ms=timeout_ms)
    if isinstance(contents, list) and all(isinstance(item, str) for item in contents):
        contents = "\n".join(contents)
    if not isinstance(contents, str):
        raise ValueError("Configured text provider does not support this multimodal helper")
    options = dict(config or {})
    unsupported = set(options) - {"system_instruction", "response_mime_type"}
    if unsupported:
        raise ValueError("Unsupported text helper options: " + ", ".join(sorted(unsupported)))
    system = options.get("system_instruction", "")
    prompt = (str(system) + "\n\n" if system else "") + contents
    if options.get("response_mime_type") == "application/json":
        prompt += "\nReturn only valid JSON."
    return SimpleNamespace(text=generate(prompt, config=settings, timeout=timeout_ms / 1000))


def as_json(contents, tier=SMART, config=None, timeout_ms=30000, default=None):
    response = call(contents, tier=tier, config=config, timeout_ms=timeout_ms)
    raw = (getattr(response, "text", "") or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
