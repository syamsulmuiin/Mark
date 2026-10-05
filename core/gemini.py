"""
One place where the assistant's one-shot Gemini calls are made.

WHY THIS EXISTS
    The live conversation runs on the Live API and is not what this file is
    about. Everything else — reading a screenshot, parsing a flight page,
    turning a request into a shell command, working out which WhatsApp button
    answers a call — was a separate `genai.Client(...)` built at the point of
    use, with the model name written inline. Sixteen files did it, twenty-six
    times, and not one of them set a timeout.

    That is not tidiness, it is three real faults:

    NO TIMEOUT.  The SDK waits forever by default. a legacy rolling alias spent
    an afternoon returning 504 DEADLINE_EXCEEDED, and every one of those calls
    became an unbounded hang — measured at ten seconds of silence while a phone
    rang, and worse elsewhere, because nothing was there to give up.

    NO FALLBACK.  One hardcoded alias meant that when that alias was unwell,
    the feature was simply gone. A ladder costs nothing when the first rung
    works and saves the feature when it does not.

    NO SINGLE PLACE TO CHANGE.  A new model release meant editing sixteen files
    and hoping none were missed.

SIDE CALL ISOLATION
    One-shot helper/diagnostic calls use REST models, not extra Live sessions. The
    interactive Live session belongs to the user conversation and must not compete
    with background/helper work for Live quota or connection slots.

THE LADDER, MEASURED
    Live, one throwaway session:
        connect                     0.24s
        short structured JSON       1.7 - 2.8s
        2300 characters of code     3.39s, not truncated
        three concurrent sessions   all fine, 4.77s wall clock
    REST text models, same prompt, same afternoon:
        legacy rolling alias        504, every time
    So REST is two to four times quicker while it lasts, and the whole point of
    the ladder is that it does not last. Pinned REST names sit behind Live;
    rolling `-latest` aliases sit behind those, because they were the ones
    having a bad day.

    Where the answer depends only on stable input, cache it and neither pool is
    touched twice: `plugins/_whatsapp_core.py` is the worked example — one
    request per WhatsApp language for the lifetime of the install.
"""
from __future__ import annotations

import asyncio
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

# A rung that means "ask the Live model instead", through a short throwaway
# session rather than the REST text API.
#
# LEGACY LIVE FALLBACK SUPPORT
#     Kept for compatibility with explicit callers; normal FAST/SMART ladders do not use it.
#     This is a voice assistant: the Live API is the dependency it already has,
#     and it draws on a DIFFERENT quota pool from the text models. On the free
#     tier the text pool is the one that runs out — an afternoon of ordinary use
#     exhausts it, and when it does, every one of these side calls fails and the
#     feature behind it dies. The Live pool is untouched by that.
#
# WHAT IT COSTS, MEASURED
#     connect                      0.24s
#     short structured JSON        1.7 - 2.8s   (REST: 0.76s)
#     2300 characters of code      3.39s, not truncated
#     three concurrent sessions    all fine, 4.77s wall clock
#     So it is two to four times slower than REST when REST is available, and
#     infinitely faster than REST when REST is out of quota.
#
# THE THING WORTH KNOWING
#     These models only speak — response_modalities=["TEXT"] is refused with a
#     1007. The reply comes back through output_transcription, which sounds like
#     it would mangle anything structured. It does not: it is the model's own
#     text of what it said, and it survived "Mum ❤ click here for contact info",
#     indented Python inside markdown fences, and src/utils/helpers_v2.py
#     character for character. That is what makes this usable at all.
#
#     What it cannot carry is grounding metadata, so grounded web search stays
#     on REST — see SEARCH.
LIVE = "live"

from core.model_config import (
    get_cooldown_policy,
    get_live_models,
    get_text_models,
)

_TEXT_MODELS = get_text_models()
_LADDERS = {
    # One-shot helper calls remain REST-only so they cannot compete with the
    # user's interactive Live conversation for a connection slot.
    FAST: _TEXT_MODELS,
    SMART: tuple(reversed(_TEXT_MODELS)),
    SEARCH: _TEXT_MODELS,
}

# The conversation's Live model has a deliberately short, compatible fallback
# list. Live models are not interchangeable with REST text models.
LIVE_MODELS = get_live_models()

# Last failed ladder is diagnostic state only; callers keep the historical None contract.
_last_call_errors: tuple[tuple[str, str], ...] = ()

def last_call_errors() -> tuple[tuple[str, str], ...]:
    return _last_call_errors

# How many one-shot Live sessions may exist at once.
#
# THE USER'S CONVERSATION OUTRANKS EVERY SIDE CALL.
# Nothing here can reach the microphone or the speaker — main.py has exactly one
# `.receive()` and it is bound to its own session, and audio only reaches the
# speaker through that one loop — so a side call cannot answer the user or talk
# over the reply. Verified alongside a live main session: four side calls fired
# while it was connected, each got its own answer, and the main session replied
# correctly both before and after with no errors.
#
# What a side call CAN do is take up a concurrent-session slot. That is the one
# way it could hurt the conversation, so it is capped, and a call that cannot
# get a slot quickly does not queue behind the others — it falls to the REST
# rung, which is what the ladder is for.
# Three, from the measurement: four side calls plus the conversation ran
# together without complaint, so three leaves the conversation a slot in hand
# while still covering any burst this app actually produces — tool calls run one
# after another, and the screen agent's loop is sequential.
_LIVE_SLOTS = threading.BoundedSemaphore(3)
_LIVE_SLOT_WAIT = 3.0

_ONE_SHOT_SYSTEM = (
    "You are a data-processing function, not an assistant and not in a "
    "conversation. There is no person listening to you. Produce exactly the "
    "output the request asks for and nothing else: no greeting, no "
    "acknowledgement, no 'Understood', no explanation, no closing remark, no "
    "restating of the question. If the request asks for JSON, emit only the "
    "JSON. If it asks for code, emit only the code. If it asks for one word, "
    "emit that one word. Preserve the exact spelling, punctuation, capitals "
    "and whitespace of anything you are asked to copy or return."
)

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

    Returns True when the caller should continue to the next model. Transport
    errors deliberately return False: walking the entire ladder cannot repair a
    broken network and only multiplies latency.
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
    if is_gone_error(error):
        _cool(model, _GONE_SECONDS)
        return True
    return False


def live_model() -> str:
    """Return the first Live model that is not resting after a model failure."""
    for model in LIVE_MODELS:
        if not _cooling(model):
            return model
    return LIVE_MODELS[0]


def note_live_failure(model: str, error: str) -> bool:
    """Record a provider/model failure and report whether to try another Live model."""
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
    from google import genai
    from google.genai import types as gtypes

    key = key or api_key()
    if not key:
        raise RuntimeError("no Gemini API key is configured")
    return genai.Client(
        api_key=key,
        http_options=gtypes.HttpOptions(timeout=max(MIN_TIMEOUT_MS, int(timeout_ms))),
    )


class _Reply:
    """What a Live turn hands back, shaped like the REST response's `.text` so
    every existing call site keeps working unchanged."""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


def _live_model() -> str:
    """Use the first currently healthy Live model for compatibility calls."""
    return live_model()


def _to_live_parts(contents) -> list:
    """REST `contents` -> Live `parts`. Accepts a bare string, a list of
    strings, and the SDK's Part objects (which is how every image is passed
    here), because those are the three shapes the call sites actually use."""
    import base64

    items = contents if isinstance(contents, (list, tuple)) else [contents]
    parts = []
    for item in items:
        if isinstance(item, str):
            parts.append({"text": item})
            continue
        blob = getattr(item, "inline_data", None)
        if blob is not None:
            data = getattr(blob, "data", None)
            mime = getattr(blob, "mime_type", None) or "application/octet-stream"
            if isinstance(data, bytes):
                data = base64.b64encode(data).decode("ascii")
            parts.append({"inline_data": {"mime_type": mime, "data": data}})
            continue
        txt = getattr(item, "text", None)
        if txt:
            parts.append({"text": txt})
            continue
        if isinstance(item, dict):
            parts.append(item)
    return parts


async def _live_turn(parts: list, system: str, key: str, timeout_s: float) -> str:
    from google import genai
    from google.genai import types as gtypes

    cl = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    # Silence the persona, or it answers instead of complying.
    #
    # These are conversational models and they behave like it: asked "Reply with
    # one word: ok" a Live turn came back with "Understood." — it treated the
    # instruction as something to acknowledge rather than something to do. The
    # REST models do not, because nobody ever taught them to be in a
    # conversation. Every call through this module wants a value, not a reply,
    # so the session is told what it is before it is told what to do.
    kwargs = {
        "response_modalities": ["AUDIO"],
        "output_audio_transcription": {},
        "system_instruction": _ONE_SHOT_SYSTEM + (f"\n\n{system}" if system else ""),
    }

    cm = cl.aio.live.connect(model=_live_model(),
                             config=gtypes.LiveConnectConfig(**kwargs))
    session = await asyncio.wait_for(cm.__aenter__(), 30)
    try:
        await session.send_client_content(
            turns={"role": "user", "parts": parts}, turn_complete=True)
        chunks: list[str] = []

        async def drain():
            async for resp in session.receive():
                sc = getattr(resp, "server_content", None)
                if sc and sc.output_transcription and sc.output_transcription.text:
                    chunks.append(sc.output_transcription.text)

        await asyncio.wait_for(drain(), timeout=timeout_s)
        # The transcription can trail the audio turn by a beat; a short second
        # drain stops a reply being cut mid-token. chat_takeover learned this
        # the same way and for the same reason.
        try:
            await asyncio.wait_for(drain(), timeout=1.5)
        except asyncio.TimeoutError:
            pass
        return "".join(chunks).strip()
    finally:
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            pass


def _live_call(contents, config, timeout_ms: int, key: str):
    """One throwaway Live session, run on its own loop in its own thread.

    A dedicated thread rather than asyncio.run() on the caller's: these are
    invoked from plugin executor threads, from UI worker threads and from
    main.py's own event loop, and asyncio.run() inside a thread that already has
    a running loop raises. Its own thread has no loop to collide with, wherever
    it was called from.

    Reconnecting costs 0.24s, so nothing is kept alive between calls — no
    session lifetime cap to manage, no GoAway to handle, no shared state.
    """
    system = ""
    if config is not None:
        system = getattr(config, "system_instruction", None) or \
            (config.get("system_instruction") if isinstance(config, dict) else "") or ""

    parts = _to_live_parts(contents)
    if not parts:
        return None

    if not _LIVE_SLOTS.acquire(timeout=_LIVE_SLOT_WAIT):
        # Every slot is busy. Do not wait it out: falling to REST costs less
        # than holding a session the user's conversation might want.
        raise RuntimeError("no free Live slot — leaving them for the conversation")

    box: dict = {}

    def runner():
        try:
            box["text"] = asyncio.run(
                _live_turn(parts, str(system), key, max(10.0, timeout_ms / 1000.0)))
        except BaseException as e:                     # noqa: BLE001
            box["error"] = e

    try:
        th = threading.Thread(target=runner, daemon=True, name="gemini-live-oneshot")
        th.start()
        th.join(timeout=max(15.0, timeout_ms / 1000.0 + 20.0))
    finally:
        _LIVE_SLOTS.release()
    if "error" in box:
        raise box["error"]
    text = box.get("text")
    return _Reply(text) if text else None


def _config_has_tools(config) -> bool:
    """Return True for both mapping and SDK config objects carrying tools.

    google.genai accepts dict configs and GenerateContentConfig-like objects.
    AFC must use Chat.send_message for either shape; otherwise the SDK warns
    when Models.generate_content receives automatic function calling tools.
    """
    if config is None:
        return False
    if isinstance(config, dict):
        return bool(config.get("tools"))
    try:
        return bool(getattr(config, "tools", None))
    except Exception:
        return False


def call(contents, tier: str = FAST, config=None,
         timeout_ms: int = DEFAULT_TIMEOUT_MS, key: str = ""):
    """Run one generation, walking the ladder until one answers.

    Returns the SDK's own response object, so callers that need more than the
    text — grounding metadata, candidates, usage — still get it. Returns None
    when every model on the ladder failed; the reason for each is printed, since
    a silent None during a session nobody can debug is how the original problem
    stayed hidden.
    """
    # `tier` is normally FAST or SMART. Anything else is taken to be an explicit
    # model name — screen_agent lets the user pick one in its settings — and it
    # is tried first, with the reasoning ladder behind it. So a user's choice is
    # honoured, and a user's choice that is having an outage still degrades to
    # something that answers instead of to nothing.
    ladder = _LADDERS.get(tier)
    if ladder is None:
        ladder = (tier,) + tuple(m for m in _LADDERS[SMART] if m != tier)

    global _last_call_errors
    _last_call_errors = ()
    resolved_key = key or api_key()
    if not resolved_key:
        print("[Gemini] no Gemini API key is configured")
        return None

    cl = None
    tried = [m for m in ladder if not _cooling(m)] or list(ladder)
    errors = []
    for model in tried:
        try:
            if model == LIVE:
                reply = _live_call(contents, config, timeout_ms, resolved_key)
                if reply is not None:
                    return reply
                raise RuntimeError("the Live turn came back empty")
            if cl is None:
                cl = client(timeout_ms=timeout_ms, key=resolved_key)
            # The SDK warns against direct Models.generate_content AFC when a
            # tool config is present. Use Chat.send_message for tool-backed
            # one-shot calls (for example grounded Google Search); plain calls
            # stay on Models.generate_content and preserve their response shape.
            _has_tools = _config_has_tools(config)
            if _has_tools:
                chat = cl.chats.create(model=model, config=config)
                return chat.send_message(contents)
            kwargs = {"model": model, "contents": contents}
            if config is not None:
                kwargs["config"] = config
            return cl.models.generate_content(**kwargs)
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
