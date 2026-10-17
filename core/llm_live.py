"""Single entry point for live provider selection.

The Gemini transport currently lives in main.py. This module enforces the
selected live provider and provides its existing Gemini model/client. Future
realtime transports must implement a compatible session interface.
"""
from __future__ import annotations
from core.setup_config import load_config


def provider(config: dict | None = None) -> str:
    settings = load_config() if config is None else config
    selected = str(settings.get("live_provider") or "gemini").strip().lower()
    if selected != "gemini":
        raise NotImplementedError(f"Live provider {selected!r} is not implemented")
    return selected


def model(config: dict | None = None) -> str:
    provider(config)
    from core.gemini import live_model
    return live_model()


def client(config: dict | None = None):
    provider(config)
    from core.gemini import client as gemini_client
    return gemini_client()


def note_model_failure(model_name: str, error: str, config: dict | None = None) -> bool:
    """Register a Gemini Live model failure without exposing its adapter to callers."""
    provider(config)
    from core.gemini import note_live_failure
    return note_live_failure(model_name, error)
