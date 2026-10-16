"""Read-only Gemini model diagnostic menu. Run: python -m core.model_diagnostics

Shows effective model priority, override sources, and cooldown policy without
printing API keys or making paid network calls.
"""
from __future__ import annotations

import os
from core import model_config as config


def _source(env_name: str, saved_name: str) -> str:
    if os.getenv(env_name, "").strip():
        return "environment"
    if config._saved_models(saved_name):
        return "local configuration"
    return "repository default"


def diagnostic_report() -> str:
    live = config.get_live_models()
    text = config.get_text_models()
    policy = config.get_cooldown_policy()
    live_source = (
        _source("ASSISTANT_LIVE_MODELS", "live_models")
        if _source("ASSISTANT_LIVE_MODELS", "live_models") != "repository default"
        else _source("ASSISTANT_LIVE_MODEL", "live_model")
    )
    text_source = (
        _source("ASSISTANT_TEXT_MODELS", "text_models")
        if _source("ASSISTANT_TEXT_MODELS", "text_models") != "repository default"
        else _source("ASSISTANT_TEXT_MODEL", "text_model")
    )
    lines = [
        "MARK — Gemini model diagnostics (offline)",
        "Live model priority: " + " -> ".join(live),
        "Live primary source: " + live_source,
        "Text/Chat priority: " + " -> ".join(text),
        "Text primary source: " + text_source,
        "Cooldown (seconds): " + ", ".join(f"{key}={value}" for key, value in policy.items()),
        "Note: This does not confirm API availability, quotas, or connectivity.",
    ]
    return "\n".join(lines)


def main() -> None:
    print(diagnostic_report())


if __name__ == "__main__":
    main()
