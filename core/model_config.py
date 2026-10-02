"""Central model and resilience configuration.

Provider model identifiers, fallback order, and retry policy live here so a
runtime/version change is made in one place instead of across call sites.
Environment overrides use product-neutral names and are optional.
"""
from __future__ import annotations

import os

DEFAULT_LIVE_MODEL = "models/gemini-3.1-flash-live-preview"
DEFAULT_LIVE_FALLBACK_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
DEFAULT_TEXT_MODEL = "gemini-flash-latest"
DEFAULT_TEXT_FALLBACK_MODEL = "gemini-flash-lite-latest"

# Ordered from the measured fast/stable models toward rolling or historically
# unavailable aliases. The ladder is intentionally configurable without changing
# call sites or placing credentials in source control.
DEFAULT_TEXT_MODELS = (
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
)

DEFAULT_QUOTA_COOLDOWN_SECONDS = 5 * 60
DEFAULT_UNAVAILABLE_COOLDOWN_SECONDS = 60
DEFAULT_PERMISSION_COOLDOWN_SECONDS = 30 * 60
DEFAULT_GONE_COOLDOWN_SECONDS = 6 * 60 * 60


def _seconds(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def get_cooldown_policy() -> dict[str, int]:
    """Return model retry delays from one product-neutral configuration point."""
    return {
        "quota": _seconds("ASSISTANT_QUOTA_COOLDOWN_SECONDS", DEFAULT_QUOTA_COOLDOWN_SECONDS),
        "unavailable": _seconds(
            "ASSISTANT_UNAVAILABLE_COOLDOWN_SECONDS",
            DEFAULT_UNAVAILABLE_COOLDOWN_SECONDS,
        ),
        "permission": _seconds(
            "ASSISTANT_PERMISSION_COOLDOWN_SECONDS",
            DEFAULT_PERMISSION_COOLDOWN_SECONDS,
        ),
        "gone": _seconds("ASSISTANT_GONE_COOLDOWN_SECONDS", DEFAULT_GONE_COOLDOWN_SECONDS),
    }


def _csv_models(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def get_live_model() -> str:
    return os.getenv("ASSISTANT_LIVE_MODEL", DEFAULT_LIVE_MODEL).strip() or DEFAULT_LIVE_MODEL


def get_live_fallback_model() -> str:
    return os.getenv("ASSISTANT_LIVE_FALLBACK_MODEL", DEFAULT_LIVE_FALLBACK_MODEL).strip() or DEFAULT_LIVE_FALLBACK_MODEL


def get_live_models() -> tuple[str, ...]:
    configured = _csv_models(os.getenv("ASSISTANT_LIVE_MODELS", ""))
    if configured:
        return configured
    return (get_live_model(), get_live_fallback_model())


def get_text_models() -> tuple[str, ...]:
    configured = _csv_models(os.getenv("ASSISTANT_TEXT_MODELS", ""))
    if configured:
        return configured

    # Explicit overrides take precedence. With defaults, use the measured ladder
    # order instead of retrying the historically unhealthy rolling aliases first.
    primary_override = os.getenv("ASSISTANT_TEXT_MODEL", "").strip()
    fallback_override = os.getenv("ASSISTANT_TEXT_FALLBACK_MODEL", "").strip()
    if primary_override or fallback_override:
        return tuple(dict.fromkeys([primary_override, fallback_override, *DEFAULT_TEXT_MODELS]))
    return DEFAULT_TEXT_MODELS


def get_text_model() -> str:
    return os.getenv("ASSISTANT_TEXT_MODEL", DEFAULT_TEXT_MODEL).strip() or DEFAULT_TEXT_MODEL


def get_text_fallback_model() -> str:
    return os.getenv("ASSISTANT_TEXT_FALLBACK_MODEL", DEFAULT_TEXT_FALLBACK_MODEL).strip() or DEFAULT_TEXT_FALLBACK_MODEL
