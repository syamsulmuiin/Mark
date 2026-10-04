"""Central model configuration for MARK-LIV.

Model identifiers live here so provider model changes do not require synchronising
hard-coded strings across the runtime and helper clients. Environment overrides
remain available for deployments that need to pin a different model.
"""
from __future__ import annotations

import os

DEFAULT_LIVE_MODEL = "models/gemini-3.8-live"
DEFAULT_LIVE_FALLBACK_MODEL = "models/gemini-3.1-flash-live-preview"
DEFAULT_TEXT_MODEL = "gemini-3.7-flash"
DEFAULT_TEXT_FALLBACK_MODEL = "gemini-3.5-flash-lite"


def get_live_model() -> str:
    return os.getenv("ASSISTANT_LIVE_MODEL", DEFAULT_LIVE_MODEL).strip() or DEFAULT_LIVE_MODEL




def get_live_fallback_model() -> str:
    return os.getenv("ASSISTANT_LIVE_FALLBACK_MODEL", DEFAULT_LIVE_FALLBACK_MODEL).strip() or DEFAULT_LIVE_FALLBACK_MODEL

def get_text_model() -> str:
    return os.getenv("ASSISTANT_TEXT_MODEL", DEFAULT_TEXT_MODEL).strip() or DEFAULT_TEXT_MODEL


def get_text_fallback_model() -> str:
    return os.getenv("ASSISTANT_TEXT_FALLBACK_MODEL", DEFAULT_TEXT_FALLBACK_MODEL).strip() or DEFAULT_TEXT_FALLBACK_MODEL
