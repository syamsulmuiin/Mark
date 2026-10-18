"""Gemini adapter for the explicitly selected Text role, plus Live model selection.
Text helpers never create Live sessions or call a different selected provider.
"""
from __future__ import annotations

import json
import sys
import time
import threading
from pathlib import Path

if getattr(sys, "frozen", False):
    _BASE = Path(sys.executable).parent
else:
    _BASE = Path(__file__).resolve().parent.parent

_KEY_FILE = _BASE / "config" / "api_keys.json"

# Ladders, tried left to right. Change a model HERE and the whole app follows.
FAST = "fast"      # short classification, extraction, one-line decisions
SMART = "smart"    # reasoning, generation, long documents, images
SEARCH = "search"  # grounded search — REST only, see below

# Retain the legacy sentinel only to reject it explicitly at the public boundary.
LIVE = "live"

from core.model_config import (
    get_cooldown_policy,
    get_live_models,
    get_text_models,
    get_chat_models,
)

_TEXT_MODELS = get_text_models()
_LADDERS = {
    # One-shot helper calls remain REST-only so they cannot compete with the
    # user's interactive Live conversation for a connection slot.
    FAST: _TEXT_MODELS,
    SMART: get_chat_models(),
    SEARCH: _TEXT_MODELS,
}

# Legacy lists are retained as configuration data; execution uses only their primary.
# Live models are never interchangeable with REST text models.
LIVE_MODELS = get_live_models()

# Last failed ladder is diagnostic state only; callers keep the historical None contract.
_last_call_errors: tuple[tuple[str, str], ...] = ()

def last_call_errors() -> tuple[tuple[str, str], ...]:
    return _last_call_errors

# Milliseconds. Not a preference: the API rejects anything under ten seconds
# with "Minimum allowed deadline is 10s", so this is the tightest bound it will
# accept. Callers with a long job (a whole document, a big image) pass more.
DEFAULT_TIMEOUT_MS = 10_000
MIN_TIMEOUT_MS = 10_000

_key_lock = threading.Lock()
_cached_key: str | None = None

# Cooldowns are intentionally different: quota refills, outages need time to
# clear, and unavailable models should not be retried for every request.
_COOLDOWN_POLICY = get_cooldown_policy()
_COOLDOWN_SECONDS = _COOLDOWN_POLICY["quota"]
_UNAVAILABLE_SECONDS = _COOLDOWN_POLICY["unavailable"]
_PERMISSION_SECONDS = _COOLDOWN_POLICY["permission"]
_GONE_SECONDS = _COOLDOWN_POLICY["gone"]
_cooldown: dict[str, float] = {}
_cool_lock = threading.Lock()


def _cool(model: str, seconds: float = _COOLDOWN_SECONDS) -> None:
    with _cool_lock:
        _cooldown[model] = time.monotonic() + seconds


def is_quota_error(error: str) -> bool:
    text = str(error)
    return "429" in text or "RESOURCE_EXHAUSTED" in text.upper()


def is_unavailable_error(error: str) -> bool:
    text = str(error)
    lower = text.lower()
    return (
        "503" in text
        or "504" in text
        or "unavailable" in lower
        or "deadline_exceeded" in lower
        or "deadline exceeded" in lower
    )


def is_permission_error(error: str) -> bool:
    text = str(error)
    lower = text.lower()
    return (
        "403" in text
        or "permission_denied" in lower
        or "permission denied" in lower
    )


def is_gone_error(error: str) -> bool:
    text = str(error)
    lower = text.lower()
    return (
        "404" in text
        or "not found" in lower
        or "is not supported" in lower
    )


def note_failure(model: str, error: str) -> bool:
    """Cool a model only when retrying it soon would repeat a model failure.

    Returns True when a model-specific cooldown was recorded. This does not
    authorize another model or provider.
    """
    if is_quota_error(error):
        _cool(model, _COOLDOWN_SECONDS)
        return True
    if is_unavailable_error(error):
        _cool(model, _UNAVAILABLE_SECONDS)
        return True
    if is_permission_error(error):
        _cool(model, _PERMISSION_SECONDS)
        return True
    if is_gone_error(error) or ("1008" in str(error) and "requested entity was not found" in str(error).lower()):
        _cool(model, _GONE_SECONDS)
        return True
    return False


def live_model() -> str:
    """Use the configured primary Live model; never silently select another."""
    return LIVE_MODELS[0]


def note_live_failure(model: str, error: str) -> bool:
    """Record a provider/model cooldown without authorizing a model switch."""
    if is_quota_error(error):
        _cool(model, _COOLDOWN_SECONDS)
        return True
    if is_unavailable_error(error):
        _cool(model, _UNAVAILABLE_SECONDS)
        return True
    if is_permission_error(error):
        _cool(model, _PERMISSION_SECONDS)
        return True
    if is_gone_error(error):
        _cool(model, _GONE_SECONDS)
        return True
    return False


def _cooling(model: str) -> bool:
    with _cool_lock:
        until = _cooldown.get(model, 0.0)
        if until and time.monotonic() < until:
            return True
        _cooldown.pop(model, None)
        return False


def api_key(refresh: bool = False) -> str:
    """The Gemini key from config/api_keys.json. Cached; never raises."""
    global _cached_key
    with _key_lock:
        if _cached_key is not None and not refresh:
            return _cached_key
        try:
            data = json.loads(_KEY_FILE.read_text(encoding="utf-8"))
            _cached_key = str(data.get("gemini_api_key") or "")
        except Exception:
            _cached_key = ""
        return _cached_key


def client(timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = ""):
    """A configured genai.Client with a deadline on it. Raises if there is no
    key, because a caller that cannot work without one should say so."""
    from core.setup_config import load_config
    if str(load_config().get("llm_provider") or "gemini").strip().lower() != "gemini":
        raise RuntimeError("Gemini Text is not the selected provider")
    from google import genai
    from google.genai import types as gtypes

    key = key or api_key()
    if not key:
        raise RuntimeError("no Gemini API key is configured")
    return genai.Client(
        api_key=key,
        http_options=gtypes.HttpOptions(timeout=max(MIN_TIMEOUT_MS, int(timeout_ms))),
    )


def call(contents, tier: str = FAST, config=None,
         timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = ""):
    """Run the configured primary Text model without model/provider fallback.

    Returns the SDK's own response object, so callers that need more than the
    text — grounding metadata, candidates, usage — still get it. Returns None
    when every model on the ladder failed; the reason for each is printed, since
    a silent None during a session nobody can debug is how the original problem
    stayed hidden.
    """
    from core.setup_config import load_config
    selected = str(load_config().get("llm_provider") or "gemini").strip().lower()
    if selected != "gemini":
        raise RuntimeError("Gemini Text is disabled: use the configured Text provider " + selected)
    if tier == LIVE:
        raise ValueError("Text requests cannot open an auxiliary Live session")
    ladder = _LADDERS.get(tier)
    if not ladder:
        raise ValueError("Configure the Text model instead of overriding it in a helper")
    # Legacy configuration can contain fallback IDs, but only its primary is authorized.
    ladder = (ladder[0],)

    global _last_call_errors
    _last_call_errors = ()
    resolved_key = key or api_key()
    if not resolved_key:
        print("[Gemini] no Gemini API key is configured")
        return None

    cl = None
    tried = [m for m in ladder if not _cooling(m)]
    if not tried:
        _last_call_errors = tuple((m, "cooldown") for m in ladder)
        return None
    errors = []
    for model in tried:
        try:
            if model == LIVE:
                raise ValueError("Live models cannot be used by the Text adapter")
            if cl is None:
                cl = client(timeout_ms=timeout_ms, key=resolved_key)
            # Use the Chat surface for every REST generation.  The google-genai
            # SDK explicitly recommends Chat.send_message for automatic function
            # calling, and using one surface here removes any config-shape blind
            # spot where a tool/AFC config could accidentally reach Models.
            # Chat returns the same GenerateContentResponse shape used by callers,
            # including candidates/grounding metadata and multimodal responses.
            chat = cl.chats.create(model=model, config=config)
            return chat.send_message(contents)
        except Exception as e:
            msg = str(e)
            errors.append((model, msg))
            if note_failure(model, msg):
                if is_quota_error(msg):
                    reason = f"out of quota — skipping it for {_COOLDOWN_SECONDS // 60} minutes"
                elif is_unavailable_error(msg):
                    reason = f"unavailable — resting it for {_UNAVAILABLE_SECONDS // 60} minutes"
                else:
                    reason = f"not available — setting it aside for {_GONE_SECONDS // 3600} hours"
                print(f"[Gemini] {model}: {reason}")
            else:
                print(f"[Gemini] {model}: {type(e).__name__}: {msg[:140]}")
    _last_call_errors = tuple(errors)
    return None


def text(contents, tier: str = FAST, config=None,
         timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = "", default: str = "") -> str:
    """`call`, reduced to the reply text. `default` when nothing answered."""
    resp = call(contents, tier=tier, config=config,
                timeout_ms=timeout_ms, key=key)
    if resp is None:
        return default
    return (getattr(resp, "text", None) or "").strip() or default


def as_json(contents, tier: str = FAST, config=None,
            timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = "", default=None):
    """`text`, parsed as JSON, tolerating the fences and prose a model wraps it
    in. `default` when nothing answered or the answer would not parse."""
    raw = text(contents, tier=tier, config=config, timeout_ms=timeout_ms, key=key)
    if not raw:
        return default
    if "{" in raw and "}" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    elif "[" in raw and "]" in raw:
        raw = raw[raw.find("["): raw.rfind("]") + 1]
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[Gemini] reply was not JSON: {e}")
        return default
