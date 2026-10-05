import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **                       kw)

    _subprocess.Popen = _Popen


# ── Console must survive non-UTF-8 code pages ────────────────────────────────
# Every status line in this file carries an emoji, and on a legacy Windows
# console the active code page is the system one — cp1254 in Turkey, cp1251 in
# Russia, cp932 in Japan. Printing an emoji there raises UnicodeEncodeError, and
# because most of these prints sit inside the receive loop it takes the session
# down on startup. Reconfiguring to UTF-8 with a replacement fallback costs
# nothing and makes the app launch the same way in every locale.
import sys as _sys

for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(_sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass          # pythonw / redirected pipes / anything exotic — never fatal

# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import os
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

from core.language_compat import (has_explicit_diagnostic_intent, is_generic_error_report,
                                  has_explicit_repair_apply_intent, has_explicit_high_risk_approval)
from core import task_continuity as task_state

import numpy as np
from google import genai
from google.genai import types
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary, pop_last_session,
    search_memory, set_trim_notifier,
)

# The file-backed tools (open_app, web_search, browser_control, …) are no longer
# imported or declared here — they self-describe via a TOOL dict in their own
# actions/*.py file and are auto-discovered by core.action_loader at startup.
# Only tools that are tied to live-session state stay inline in this file
# EXPLICIT SERVER SHUTDOWN ONLY: never use for ending a conversation/session or farewell intent.
# (screen_process, close_camera, save_memory, manage_monitor, shutdown_jarvis,
# system_status).
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine
from actions.scheduled_workflow import due_workflows
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from memory.config_manager     import (
    get_media_resolution, get_proactive_audio_enabled,
    get_push_to_talk_enabled, get_thinking_enabled, get_turn_tuning, get_voice,
    get_wake_word_enabled, save_wake_word_enabled,    get_input_device, get_output_device,
)
from core.plugin_loader        import discover_plugins
from core                      import undo as undo_stack
from core                      import confirm as confirm_gate
from core.action_loader        import discover_actions
from core.echo                 import EchoGuard
from core.viseme               import VisemeStream
from core.wake_word            import (
    WakeWordDetector, is_ready as wake_is_ready, install_and_download as wake_install,
)

# How long the assistant stays awake with no user speech before it auto-sleeps
# again (wake-word mode only).
WAKE_SLEEP_TIMEOUT = 120.0   # seconds (2 minutes)

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
_TRACE_LOG      = BASE_DIR / "runtime" / "interaction.log"

def _trace_event(event: str, **fields) -> None:
    """Write bounded session diagnostics without audio/text payloads."""
    try:
        _TRACE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": round(time.time(), 3), "event": event, **fields}, separators=(",", ":")) + "\n")
    except Exception:
        pass

from core import gemini as _gemini
from core.runtime_errors import Boundary, ErrorAction, classify_error
from core.model_config import get_live_model
LIVE_MODEL          = get_live_model()
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000 
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

# RMS below which 16-bit PCM is treated as room silence; above _LEVEL_FULL it
# reads as a full-height waveform. Tuned so ordinary speech lands mid-range and
# the bars still move for a quiet talker — language- and device-independent.
_LEVEL_FLOOR = 60.0
_LEVEL_FULL  = 2600.0


def _pcm_level(samples) -> float:
    """Map a block of int16 PCM samples to a 0.0–1.0 loudness level for the HUD
    waveform. Returns 0.0 on empty/invalid input so it can never raise."""
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(x * x)))
    except Exception:
        return 0.0
    if rms <= _LEVEL_FLOOR:
        return 0.0
    return min(1.0, (rms - _LEVEL_FLOOR) / (_LEVEL_FULL - _LEVEL_FLOOR))


# ── Viseme extraction ─────────────────────────────────────────────────────────
# The avatar's mouth used to be driven by one RMS value per ~200 ms write batch,
# which is five updates a second averaged over a fifth of a second — it could
# only ever flap. These read the *shape* of each 20 ms slice straight from the
# spectrum of the audio being played, so no transcript, no forced alignment and
# no language assumption: it works the same for Turkish and English.
#
# Two numbers come out. Openness tracks the first formant — F1 climbs as the jaw
# drops, so /a/ reads open and /i/ or /u/ read closed. Width tracks the second —
# F2 is high for spread vowels (/i/, /e/) and low for rounded ones (/u/, /o/).
# Extra time beyond the device's reported output latency before the microphone
# is trusted again: covers room decay and the speaker's own settling.
_TAIL_MARGIN = 0.25

_VIS_WIN = 1024        # ~43 ms analysis window at 24 kHz: enough for formants
_VIS_HOP = 480         # 20 ms between frames, i.e. 50 shapes a second

# Delay from handing the first bytes of a reply to an already-running output
# stream to hearing them: one callback period, plus whatever the DAC adds.
_FIRST_SOUND = CHUNK_SIZE / RECEIVE_SAMPLE_RATE      # ~43 ms
# How far past the device's own buffer the mouth's timeline may drift before it
# is re-anchored. The buffer is the hard limit on how much audio can be queued
# ahead, so anything beyond it plus a margin for clock error is impossible.
_CURSOR_SLACK = 0.15

# Erring early is the safe direction. A viewer tolerates a mouth that moves
# slightly before the sound far better than one that moves after it — the
# broadcast limits are about 45 ms of lag against 125 ms of lead — so where
# this is uncertain it is biased to lead.


def _pcm_visemes(samples, sr: int = 24000):
    """Slice a PCM block into (level, openness, width) frames, one per 20 ms.

    Returns [] on anything unexpected — the mouth falls back to loudness-only
    articulation rather than the caller having to handle an error.
    """
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size < _VIS_WIN:
            return []
        win = np.hanning(_VIS_WIN).astype(np.float32)
        freqs = np.fft.rfftfreq(_VIS_WIN, 1.0 / sr)
        b_f1_lo = (freqs >= 150) & (freqs < 450)     # F1 of close vowels
        b_f1_hi = (freqs >= 450) & (freqs < 1100)    # F1 of open vowels
        b_f2_bk = (freqs >= 600) & (freqs < 1300)    # F2 of rounded vowels
        b_f2_fr = (freqs >= 1700) & (freqs < 3200)   # F2 of spread vowels
        b_hiss = (freqs >= 3800) & (freqs < 8000)    # fricatives

        # One frame per hop across the *whole* block. Stepping only while a full
        # window fits stopped 1024 - 480 samples short of the end, so a 200 ms
        # batch yielded 160 ms of schedule: the mouth ran out of frames before
        # the audio ran out of sound, and each batch no longer lined up with the
        # end of the one before it. Losing 20 % of every batch is most of why
        # the mouth did not track the words.
        out = []
        for start in range(0, x.size, _VIS_HOP):
            # The level gates closures, so it is measured over exactly this
            # 20 ms and never looks ahead. The spectrum needs a longer window
            # to resolve formants and may be short-filled at the very end.
            level = _pcm_level(x[start:start + _VIS_HOP])
            seg = x[start:start + _VIS_WIN]
            if seg.size < _VIS_WIN:
                seg = np.concatenate([seg, np.zeros(_VIS_WIN - seg.size,
                                                    dtype=np.float32)])
            if level <= 0.0:
                out.append((0.0, 0.0, 0.0))
                continue
            mag = np.abs(np.fft.rfft((seg - seg.mean()) * win))
            f1l, f1h = float(mag[b_f1_lo].sum()), float(mag[b_f1_hi].sum())
            f2b, f2f = float(mag[b_f2_bk].sum()), float(mag[b_f2_fr].sum())
            hiss = float(mag[b_hiss].sum())

            openness = f1h / (f1l + f1h + 1e-6)
            width = (f2f - f2b) / (f2f + f2b + 1e-6)
            # A wide-open jaw physically cannot purse, so openness damps width.
            # /a/ has a low enough F2 to read as "rounded" on the bands alone;
            # letting openness suppress the width term is what keeps an open
            # vowel from pursing.
            width *= (1.0 - openness) ** 0.8
            # Fricatives are formed with a nearly closed mouth.
            h = hiss / (f1l + f1h + f2b + f2f + hiss + 1e-6)
            openness *= 1.0 - 0.65 * min(1.0, h * 2.5)
            out.append((level,
                        float(min(1.0, max(0.0, openness))),
                        float(min(1.0, max(-1.0, width)))))
        return out
    except Exception:
        return []


def _describe_tools(declarations) -> str:
    """One line per capability, straight from the live tool declarations.

    Derived rather than written down: the action and plugin registries are
    discovered at startup, so whatever the user has installed is what the model
    is told it can do. Adding a plugin extends this by itself, and removing one
    stops the model from claiming an ability it no longer has.
    """
    lines = []
    for d in declarations or ():
        try:
            name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
            desc = (d.get("description") if isinstance(d, dict)
                    else getattr(d, "description", "")) or ""
        except Exception:
            continue
        if not name:
            continue
        desc = " ".join(str(desc).split())
        lines.append(f"- {name}: {desc[:150]}" if desc else f"- {name}")
    return "\n".join(lines)


def _describe_limits(has_vision: bool, has_mic: bool, has_device_mesh: bool = False) -> str:
    """The other half of self-knowledge: what is out of reach, and why.

    Derived from how the program is actually built, not from a list of refusals.
    A model that knows its boundaries stops improvising around them, and stating
    them as architecture rather than as rules keeps the answer honest in any
    language.
    """
    out = [
        "- Anything not listed above is outside your reach. Say so in one clause "
        "and offer the nearest thing you can actually do — never mime an action "
        "you cannot take, and never report a result you did not get.",
        ("- You can control this machine and trusted paired devices through the tools listed above." if has_device_mesh else "- You act on this machine only. You cannot reach the user's other devices, accounts or hardware except through the tools listed above."),
        "- You remember what is in the memory block and what has been said this "
        "session. Anything else you were told before is gone unless it was saved.",
    ]
    if has_vision:
        out.append(
            "- Your sight is not continuous. You see nothing until you call a "
            "vision tool, and then only that single frame at that moment — you "
            "cannot watch, monitor or notice something changing on screen.")
    else:
        out.append("- You have no sight at all in this build.")
    if has_mic:
        out.append(
            "- You hear nothing while the microphone is muted, and you cannot "
            "unmute it yourself.")
    return "\n".join(out)


def _render_prompt(template: str, values: dict) -> str:
    """Fill {tokens} in the prompt template.

    A plain replace rather than str.format: the file is meant to be edited by
    hand, and a stray brace in someone's own wording must never take the app
    down at startup.
    """
    out = template or ""
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

# Transcript chunks shorter than this may legitimately repeat ("evet, evet"),
# so only longer ones are treated as duplicates.
_REPEAT_MIN = 12


def _is_repeat_chunk(txt: str, buf: list) -> bool:
    """True if this transcript chunk has already been seen this turn.

    Guards against the API re-sending the tail of a response across the several
    turn_completes a tool-using turn produces.
    """
    if len(txt) < _REPEAT_MIN:
        return bool(buf) and txt == buf[-1]
    joined = " ".join(buf)
    return txt in joined

def _clean_transcript(text: str) -> str:
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()


def _partial_transcript_entries(input_chunks: list[str], output_chunks: list[str], assistant_name: str) -> list[tuple[str, str]]:
    """Return unfinished turn text so a provider rollover cannot erase context."""
    entries = []
    incoming = " ".join(x for x in input_chunks if x).strip()
    outgoing = " ".join(x for x in output_chunks if x).strip()
    if incoming:
        entries.append(("user", incoming))
    if outgoing:
        entries.append(("jarvis", outgoing))
    return entries

from core.live_tools import TOOL_DECLARATIONS


class _ReconnectSignal(Exception):
    """Raised inside the session TaskGroup to force a clean, voluntary reconnect
    (e.g. the user picked a new voice — the voice is fixed at connect time, so
    the session must be rebuilt).

    Carries `keep_context`: True for an ordinary rebuild, where the stored
    resumption handle is replayed and the conversation continues; False when the
    new session must genuinely start clean (see the voice-change note in
    _on_voice_change)."""

    def __init__(self, keep_context: bool = True):
        super().__init__()
        self.keep_context = keep_context


def _is_reconnect_signal(exc: BaseException) -> bool:
    """True if `exc` is a _ReconnectSignal, or a(n) (Base)ExceptionGroup that
    wraps one — TaskGroup bundles child exceptions into a group."""
    if isinstance(exc, _ReconnectSignal):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_reconnect_signal(sub) for sub in exc.exceptions)
    return False


def _exception_text(exc: BaseException) -> str:
    """Flatten TaskGroup/BaseExceptionGroup messages for transport classification.

    Python 3.11 TaskGroup stringifies a group as only "unhandled errors in a
    TaskGroup", hiding the child API/WebSocket error.  Transport rollover
    detection must inspect the nested exception text as well.
    """
    parts = [str(exc)]
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            parts.append(_exception_text(sub))
    return "\n".join(part for part in parts if part)


def _bounded_exception_text(exc: BaseException, limit: int = 600) -> str:
    """Return a short diagnostic without persisting credential-like values."""
    text = " ".join(_exception_text(exc).split())
    text = re.sub(
        r"(?i)(api[_ -]?key|token|authorization|bearer|password|secret)\\s*[:=]\\s*[^\\s,;]+",
        r"\\1=[REDACTED]",
        text,
    )
    return text[:limit]


def _is_transient_transport_error(exc: BaseException) -> bool:
    """Classify temporary network/WebSocket failures that should reconnect quietly.

    Gemini Live can wrap the original socket error in APIError 1006 and then in
    a TaskGroup ExceptionGroup. Inspect the complete nested text so Windows
    transport failures do not become misleading application tracebacks.
    """
    text = _exception_text(exc).lower()
    markers = (
        "1006", "1011", "abnormal closure", "no close frame received or sent",
        "timeouterror", "timed out", "getaddrinfo", "cancellederror",
        "connectionrefusederror", "connectionabortederror",
        "connectionreseterror", "connectionerror", "oserror",
        "cannot connect", "network is unreachable",
        "remote computer refused", "network connection was aborted",
        "winerror 64", "network name is no longer available",
        "winerror 121", "semaphore timeout period has expired",
        "winerror 1225", "winerror 1236",
    )
    return any(marker in text for marker in markers)


def _keep_context_of(exc: BaseException) -> bool:
    """Read `keep_context` off a reconnect signal, unwrapping the group the
    TaskGroup put it in. Defaults to True: an unexpected shape must not silently
    wipe the conversation."""
    if isinstance(exc, _ReconnectSignal):
        return getattr(exc, "keep_context", True)
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            if _is_reconnect_signal(sub):
                return _keep_context_of(sub)
    return True


class JarvisLive:
    def __init__(self, ui):
        self.ui             = ui
        self._asst_name     = "JARVI    S"   # updated each session from config
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                     = None
        self._tool_progress_task   = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._phone_activity_active = False
        self._phone_last_voice     = 0.0
        self._last_audio_queue_full_log = 0.0
        self._pending_vision       = None    # (session_generation, img_bytes, mime_type, question, angle)
        self._session_generation    = 0       # increments for every Live connection; stale vision is never replayed
        self._blocked_device_action = None    # exact rejected device action; requires re-inspect/replan before retry
        self._tool_turn_cache = {}          # idempotency: one identical tool+args execution per user turn
        self._attachment_turn = None          # one logical attachment transaction per user turn
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        # Transcript-driven mouth shapes for the avatar. Fed from the receive
        # loop as words arrive, drained by the playback loop against the audio.
        self._visemes              = VisemeStream()
        self._last_out_logged      = ""      # de-dupes a re-sent transcript tail
        # Push-to-talk
        self._ptt_enabled          = False
        self._ptt_held             = False
        self._ptt                  = None    # core.hotkey.PushToTalk
        self._out_level            = 0.0     # level of the audio being played right now
        self._echo                 = EchoGuard()
        # `stream.write()` returns when the buffer accepts the audio, not when the
        # speaker has finished with it, so sound is still in the room after the
        # speaking flag drops. Streaming the microphone during that gap is how an
        # assistant ends up answering itself. Measured from the device rather than
        # guessed; see _play_audio.
        self._out_latency          = 0.20    # seconds, replaced with the real value
        self._tail_until           = 0.0     # monotonic time the echo tail expires
        # Wall-clock time at which the audio written next will begin to sound.
        # The mouth is scheduled against this, never against "now": batches are
        # handed to the device far faster than they play, so "now" ran the lips
        # ahead of the words and cut every schedule short. 0 = nothing playing.
        self._play_cursor          = 0.0
        # Monotonic deadline used to pace PCM relay to the companion. Gemini can
        # deliver many audio frames in one burst; forwarding them immediately
        # overloads the client queue and sounds intermittent on mobile networks.
        self._audio_relay_cursor   = 0.0
        self.ui.on_push_to_talk   = self.set_push_to_talk
        self.ui.ptt_hold          = self._on_ptt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_voice_change   = self._on_voice_change     # voice picker → rebuild session
        self.ui.on_audio_device_change = self._on_audio_device_change
        self._reconnect_event: asyncio.Event | None = None
        self._reconnect_keep = True   # False → next rebuild drops the resumption handle

        # ── Session resumption ─────────────────────────────────────────
        # The server issues a resumption handle every few seconds and reissues
        # it as the conversation moves on. Before this, session_resumption was
        # switched ON in the config and the update was never read, so the handle
        # was thrown away and EVERY reconnect — a dropped packet, a voice change,
        # switching microphone — started an empty session. "Unlimited sessions"
        # leaked through exactly this hole.
        #
        # Deliberately in RAM only, never written to disk. Persisting it would
        # make a fresh launch continue yesterday's conversation, which sounds
        # appealing but breaks the session-summary flow: _save_session_summary
        # runs at shutdown and the morning briefing pops it the next day. A
        # conversation that never ends never produces a summary, and the
        # "yesterday we talked about…" line silently disappears.
        self._resume_handle: str | None = None
        self._recovery_context_pending = False  # inject local transcript if a server resumption handle expires
        self._turn_done_event: asyncio.Event | None = None
        # Live-session liveness. A WebSocket can remain open while the provider
        # stops producing turn events, so exception-only reconnect logic is not
        # sufficient. Voice boundaries are tracked independently from transport.
        self._live_progress_seq = 0
        self._voice_turn_seq = 0
        self._pending_voice_turns: list[tuple[int, float, int]] = []
        self._unanswered_voice_turns = 0
        self._live_stall_timeout = 12.0
        # Semantic barge-in: speech heard while the assistant is talking is only
        # a candidate. Android uses VOICE_COMMUNICATION/AEC and keeps streaming
        # mic PCM during playback; the server buffers that candidate and asks a
        # multilingual model whether its meaning is an interruption/correction.
        self._barge_audio = bytearray()
        self._barge_voice_active = False
        self._barge_last_voice = 0.0
        self._barge_classifying = False
        self._barge_max_bytes = SEND_SAMPLE_RATE * 2 * 8  # max 8 seconds PCM16
        self._dashboard     = None
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._session_log: list[str] = []
        self._last_repair_plan_id: str = ""
        self._current_user_transcript: str = ""          # conversation turns for end-of-session summary

        self._enhanced_live = True  # proactive audio; auto-disabled if the server rejects it
        self._tuned_live    = True  # turn-taking / media / thinking knobs; same fallback

        _base_dir = Path(__file__).resolve().parent
        _inline_names = {t["name"] for t in TOOL_DECLARATIONS}

        # File-backed tools: every actions/*.py with a TOOL dict, discovered the
        # same way plugins are. Reserved names = the inline tools above, so an
        # action can never shadow one.
        # Only server-capable actions are imported here. Device/UI actions live in
        # the companion packages and are reached through advertised capabilities.
        _server_actions = {
            "browser_control", "code_helper", "dev_agent", "file_processor",
            "flight_finder", "scheduled_workflow", "self_repair_apply",
            "self_repair_diagnostic", "autonomous_goal", "weather_report", "web_search",
        }
        self._action_registry = discover_actions(
            actions_dir=_base_dir / "actions",
            reserved_names=_inline_names,
            logger=lambda msg: print(f"[Actions] {msg}"),
            allowed_names=_server_actions,
        )

        # Plugins must not collide with either an inline tool or a discovered action.
        _core_names = _inline_names | self._action_registry.names()
        self._plugin_registry = discover_plugins(
            plugins_dir=_base_dir / "plugins",
            core_tool_names=_core_names,
            # Console gets the full boot transcript; the activity log gets only
            # what the user has to know about. Every plugin loading correctly is
            # the expected case and does not belong in their conversation.
            logger=lambda msg: print(f"[Plugins] {msg}"),
            notify=lambda msg: self.ui.write_log(f"SYS: {msg}"),
        )
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.get_plugin_settings = self._plugin_registry.settings_schemas  # ⚙ settings tab
        self.ui.request_say = self.plugin_say   # plugins: mid-task speech channel

        # ── Wake word ────────────────────────────────────────────────────────
        # _awake gates the mic (see _listen_audio) and the background speakers.
        # It is True whenever wake word is OFF, so default behaviour is unchanged.
        self._wake_enabled     = get_wake_word_enabled()
        self._awake            = not self._wake_enabled
        self._wake_detector: WakeWordDetector | None = None
        self._wake_sleep_timeout = WAKE_SLEEP_TIMEOUT

        # Restore the saved push-to-talk preference. Doing it here rather than
        # in __init__ means the hotkey thread only exists once there is a
        # session to talk to.
        if get_push_to_talk_enabled():
            try:
                self.set_push_to_talk(True)
            except Exception as e:
                print(f"[JARVIS] ⚠ Push-to-talk unavailable: {e}")
        # UI control surface for the Wake Word settings section.
        self.ui.wake_is_ready    = wake_is_ready          # () -> bool
        self.ui.wake_get_state   = self._wake_state       # () -> dict
        self.ui.on_wake_toggle   = self._ui_wake_toggle   # (enable: bool) -> str
        self.ui.on_wake_manual   = self._ui_wake_manual   # () -> toggle awake/asleep
        self.ui.on_wake_install  = self._ui_wake_install  # () -> (ok, msg)

    # ── Wake word: state machine ─────────────────────────────────────────────

    def _wake_state(self) -> dict:
        # A loaded, running detector is definitively ready; otherwise fall back
        # to the cheap on-disk model-file check (no Model construction).
        ready = bool(self._wake_detector and self._wake_detector.ready) or wake_is_ready()
        return {"enabled": self._wake_enabled, "awake": self._awake, "ready": ready}

    def _ensure_wake_detector(self) -> bool:
        """Load the detector once (model loads on first start). Idempotent."""
        if self._wake_detector is None:
            self._wake_detector = WakeWordDetector(
                on_detect=self._on_wake_detected,
                logger=lambda m: print(f"[Wake] {m}"),
                notify=lambda m: self.ui.write_log(f"SYS: {m}"),
            )
        if not self._wake_detector.ready:
            return self._wake_detector.start()
        return True

    def _on_wake_detected(self) -> None:
        """Called from the detector thread when 'Hey Jarvis' is heard."""
        self.wake(reason="wake word")

    def wake(self, reason: str = "wake word") -> None:
        if self._awake:
            return
        self._awake = True
        self._last_user_speech = time.monotonic()   # start the auto-sleep clock now
        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        self.ui.write_log(f"SYS: Awake — {reason}.")

    def sleep(self, reason: str = "timeout") -> None:
        if not self._awake:
            return
        self._awake = False
        self.set_speaking(False)
        self.ui.set_state("SLEEPING")
        self.ui.write_log(f"SYS: Sleeping — {reason}. Say 'Hey Jarvis' to wake me.")

    async def _run_sleep_watch(self) -> None:
        """Auto-sleep after the configured silence window (wake-word mode only)."""
        while True:
            await asyncio.sleep(5)
            if not self._wake_enabled or not self._awake:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue
            if (time.monotonic() - self._last_user_speech) > self._wake_sleep_timeout:
                self.sleep(reason="no speech for 2 minutes")

    # ── Wake word: UI callbacks (called from the Qt thread) ──────────────────

    def _ui_wake_toggle(self, enable: bool) -> str:
        """Enable/disable wake word from the settings UI. Returns a status token:
        'enabled' | 'disabled' | 'need_download'."""
        if enable:
            if not wake_is_ready():
                return "need_download"
            self._wake_enabled = True
            save_wake_word_enabled(True)
            self._ensure_wake_detector()
            self.sleep(reason="wake word enabled")
            return "enabled"
        else:
            self._wake_enabled = False
            save_wake_word_enabled(False)
            self.wake(reason="wake word disabled")
            return "disabled"

    def _ui_wake_manual(self) -> None:
        """Manual sleep/wake button in the UI."""
        if not self._wake_enabled:
            return
        if self._awake:
            self.sleep(reason="you tapped sleep")
        else:
            self.wake(reason="you tapped wake")

    def _ui_wake_install(self) -> tuple[bool, str]:
        """Download openwakeword + the model (runs in a UI worker thread)."""
        # Triggered by the user pressing the button, so its progress is exactly
        # what they are waiting to see.
        return wake_install(logger=lambda m: print(f"[Wake] {m}"),
                            notify=lambda m: self.ui.write_log(f"SYS: {m}"))

    def plugin_say(self, instruction: str) -> None:
        """
        Thread-safe speech channel for plugins: lets a plugin ask JARVIS to
        say something short WHILE its run() is still executing (plugins block
        their executor thread, so they can't speak through the tool response
        until they finish). The instruction is injected into the Live session
        exactly like a proactive check-in; Gemini phrases it naturally in the
        user's language. Silently a no-op when no session is connected.
        """
        loop = getattr(self, "_loop", None)
        if not loop or not self.session:
            return

        async def _say():
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": instruction}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[PluginSay] {e}")

        try:
            asyncio.run_coroutine_threadsafe(_say(), loop)
        except Exception as e:
            print(f"[PluginSay] {e}")

    def request_reconnect(self, keep_context: bool = True, reason: str = ""):
        """Thread-safe: ask the run loop to tear down and rebuild the Live
        session. Called from the Qt thread. No-op until the async loop and
        reconnect event exist.

        `keep_context=False` drops the resumption handle so the new session
        starts empty — only for changes the server cannot apply to a resumed
        session."""
        loop = getattr(self, "_loop", None)
        ev   = self._reconnect_event
        self._reconnect_keep   = keep_context
        self._reconnect_reason = reason
        if loop and ev is not None:
            loop.call_soon_threadsafe(ev.set)

    def _on_voice_change(self):
        """Voice picker applied.

        The voice is baked into the session at connect time, so a rebuild is
        required. It is rebuilt WITHOUT the resumption handle on purpose:
        resuming restores the server's own session state, and the safe reading
        is that it restores the voice with it — which would make the picker
        appear to do nothing. Losing context here is acceptable because changing
        voice is a deliberate, rare act; losing it on a dropped packet was not."""
        self.request_reconnect(keep_context=False, reason="new voice")

    def _on_audio_device_change(self):
        """Microphone or speaker changed. Both streams are opened inside the
        session TaskGroup, so they can only be re-opened by rebuilding it —
        but the conversation is kept, which is the whole reason resumption
        landed before this feature did."""
        self.request_reconnect(keep_context=True, reason="audio device")

    async def _watch_reconnect(self):
        """Session-scoped task: when a voluntary reconnect is requested, raise a
        signal that unwinds the TaskGroup so the run loop rebuilds the session."""
        assert self._reconnect_event is not None
        await self._reconnect_event.wait()
        self._reconnect_event.clear()
        keep   = self._reconnect_keep
        reason = getattr(self, "_reconnect_reason", "") or "settings"
        self.ui.write_log(
            f"SYS: Applying {reason} — reconnecting"
            + ("..." if keep else " (starting a fresh conversation)...")
        )
        raise _ReconnectSignal(keep_context=keep)

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        self.ui.write_log(
            "SYS: Remote pairing now requires a companion-issued request and operator-approved one-time code."
        )
        return None

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        # Respect wake-word sleep: a typed command must not be answered while
        # asleep either (the sleep gate is not just for the mic). Wake first with
        # "Hey Jarvis" or the WAKE NOW button.
        if self._wake_enabled and not self._awake:
            self.ui.write_log("SYS: I'm asleep — say 'Hey Jarvis' or tap WAKE NOW first.")
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def _tail_active(self) -> bool:
        """True while the speakers may still be finishing our last sentence."""
        return time.monotonic() < self._tail_until

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self._tail_until = 0.0
        else:
            # Hold the guard open across the device's own output latency plus a
            # margin for the room. The microphone is NOT muted during it — the
            # guard still lets a genuine reply through, so answering instantly
            # still works. Only our own echo is dropped.
            self._tail_until = time.monotonic() + self._out_latency + _TAIL_MARGIN
        if not value:
            # The echo history is deliberately NOT cleared here: the tail above
            # still needs it to recognise our own voice. It is dropped when the
            # tail expires. What the guard learned about the room always stays.
            self._out_level = 0.0
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

        # Companion audio is half-duplex.  The server UI is headless, so changing
        # only the local interface state leaves the companion microphone paused
        # forever after the first audio frame.  Mirror the live speaking state to
        # authenticated companions so only the active client pauses while JARVIS
        # speaks and resumes immediately when the turn has drained.
        if self._dashboard:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._dashboard.broadcast({
                    "type": "status",
                    "state": "speaking" if value else "listening",
                }))
            except RuntimeError:
                pass

    def set_thinking(self):
        """Publish a real model-processing state before response audio starts."""
        if self._is_speaking:
            return
        self.ui.set_state("THINKING")
        if self._dashboard:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._dashboard.broadcast({
                    "type": "status",
                    "state": "thinking",
                }))
            except RuntimeError:
                pass

    async def _tool_progress_heartbeat(self, tool_name: str):
        """Keep the paired companion visibly alive during long server work.

        Tool execution is awaited inside the Live receive loop, so no spoken
        response can arrive until the tool returns.  Send a sparse transcript
        heartbeat after the first delay; this is status only, not a new model
        turn, and therefore cannot interrupt or corrupt the active task.
        """
        labels = {
            "code_helper": "pembuatan dokumen/kode",
            "dev_agent": "pekerjaan pengembangan",
            "web_search": "pencarian informasi",
            "self_repair_diagnostic": "diagnostik sistem",
            "send_server_file": "pengiriman berkas",
            "transfer_file": "transfer berkas",
        }
        label = labels.get(str(tool_name), "pekerjaan yang diminta")
        try:
            await asyncio.sleep(8)
            while True:
                if self._dashboard:
                    await self._dashboard.broadcast({
                        "type": "status",
                        "state": "thinking",
                        "progress": f"Masih memproses {label}. Companion tetap terhubung.",
                    })
                    await self._dashboard.broadcast({
                        "type": "log",
                        "speaker": "jarvis",
                        "text": f"Masih memproses {label}; belum selesai.",
                        "progress": True,
                        "ts": datetime.now().isoformat(),
                    })
                await asyncio.sleep(20)
        except asyncio.CancelledError:
            raise

    def set_push_to_talk(self, enabled: bool) -> str:
        """Turn hold-to-talk on or off. Returns the scope actually achieved."""
        from core.hotkey import PushToTalk

        self._ptt_enabled = bool(enabled)
        self._ptt_held = False
        if not enabled:
            if self._ptt is not None:
                self._ptt.stop()
                self._ptt = None
            return "off"

        if self._ptt is None:
            self._ptt = PushToTalk(self._on_ptt)
        scope = self._ptt.start()
        # A window-scoped chord is a real limitation, not a detail — say it once
        # in the log so nobody wonders why it does nothing while another app is
        # focused. Reporting it must never be able to undo the thing it reports.
        try:
            self.ui.write_log(
                f"SYS: Push-to-talk on — hold {self._ptt.label}"
                + ("." if scope == "global"
                   else " (works while this window is focused)."))
        except Exception:
            pass
        return scope

    def _on_ptt(self, held: bool) -> None:
        """Chord pressed or released — may arrive on the hotkey thread."""
        self._ptt_held = held
        if held:
            # Holding the key is also a way to wake it, so push-to-talk works
            # without having to say the wake word first.
            if self._wake_enabled and not self._awake:
                self._awake = True
                self._last_user_speech = time.monotonic()
        try:
            self.ui.set_state("LISTENING" if held else "SLEEPING")
        except Exception:
            pass

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        # The words we were about to mouth are never going to be spoken now.
        self._visemes.reset()
        self._play_cursor = 0.0     # next batch starts a fresh timeline
        self._audio_relay_cursor = 0.0
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        # Load customization from config
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or "JARVIS").strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = "JARVIS"
            _user_name = ""

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        # Identity injection — overrides any hardcoded name in prompt.txt
        # Address form is a property of the language being spoken, so it is
        # stated as a principle rather than a two-language lookup — the model
        # already knows the respectful register of whatever language it is in.
        _addr = (f"ADDRESS: Always call the user '{_user_name}'."
                 if _user_name
                 else 'ADDRESS: Address the user with the ordinary respectful form '
                      'for a superior in the language you are currently speaking — '
                      '"sir" in English, its everyday equivalent in any other '
                      'language. Never an archaic or aristocratic form, and never '
                      'the form from a different language than the one you are '
                      'speaking in this sentence.')
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. "
            f"Always refer to yourself as {self._asst_name}.\n"
            f"{_addr}\n\n"
        )

        # Everything the model is told about *itself* is derived here, not
        # written into prompt.txt: the name comes from config, the platform from
        # the host, the capability list from the registries that were just
        # discovered. Rename the assistant, add a plugin or move to another OS
        # and this follows without anyone editing a prompt.
        # Build the Live tool list once per function name.  Gemini Live rejects
        # the entire session when the same declaration is present twice (1007).
        # Registries already guard normal name collisions, but deduplicating at
        # the final API boundary also protects against a stale/third-party
        # registry returning an inline declaration such as list_paired_devices.
        _decl_candidates = (TOOL_DECLARATIONS
                            + self._action_registry.get_tool_declarations()
                            + self._plugin_registry.get_tool_declarations())
        _all_decls = []
        _decl_names = set()
        for _decl in _decl_candidates:
            _name = (_decl.get("name") if isinstance(_decl, dict)
                     else getattr(_decl, "name", ""))
            if not _name or _name in _decl_names:
                continue
            _decl_names.add(_name)
            _all_decls.append(_decl)
        _names = set(_decl_names)
        sys_prompt = _render_prompt(sys_prompt, {
            "assistant_name": self._asst_name,
            "platform": f"{_platform.system()} {_platform.release()}".strip(),
            "capabilities": _describe_tools(_all_decls),
            "limits": _describe_limits(
                has_vision="screen_process" in _names,
                has_mic=True,
                has_device_mesh="call_paired_device" in _names,
            ),
        })

        parts = [identity_ctx]
        if mem_str:
            parts.append(mem_str)
        # A Live resumption handle can expire at the provider's hard session
        # rollover. Keep continuity by carrying our already-captured transcript
        # into the replacement session as context instead of pretending the
        # conversation vanished. This is only used after an actual rejected
        # resumption handle; normal fresh launches remain fresh.
        if self._recovery_context_pending and self._session_log:
            recent = "\n".join(self._session_log[-40:])
            parts.append(
                "SESSION ROLLOVER CONTEXT (reference only; do not answer, repeat, summarize, or act on this block unless the user sends a new request):\n"
                + recent
            )
        _task_recovery = task_state.recovery_instruction()
        if _task_recovery:
            parts.append(_task_recovery)
        parts.append(sys_prompt)

        cfg = dict(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": _all_decls}],
            # Hand back the handle captured from the last session_resumption
            # update. `handle=None` is exactly the old behaviour (ask for
            # handles, start fresh), so the first connect of a run is unchanged.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resume_handle
            ),
            # Sliding-window compression: session never dies from a full context
            # window — JARVIS can stay in one conversation for hours
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=get_voice()
                    )
                )
            ),
        )
        if self._enhanced_live:
            # Proactive audio: JARVIS stays silent when speech isn't addressed
            # to it (background chatter, talking to someone else in the room).
            # (Affective dialog was dropped: gemini-3.1-flash-live does not
            #  support it, and it never reliably detected tone in practice.
            #  To restore it on a 2.5 native-audio model, add back:
            #  cfg["enable_affective_dialog"] = True )
            if get_proactive_audio_enabled():
                cfg["proactivity"] = types.ProactivityConfig(proactive_audio=True)

        if self._tuned_live:
            cfg.update(self._tuning_config())

        return types.LiveConnectConfig(**cfg)

    def _tuning_config(self) -> dict:
        """The optional knobs, kept apart so one bad field can be dropped wholesale.

        Every one of these is a preview-API field. If a future model release
        stops accepting any of them the connection fails at setup, so the run
        loop turns `_tuned_live` off and reconnects on the plain config rather
        than leaving the user with an assistant that will not start.
        """
        out: dict = {}

        # Phone audio is bounded by the companion relay, which emits explicit
        # ActivityStart/ActivityEnd events after measuring PCM. Do not also send
        # Gemini automatic activity detection: mixing automatic and manual turn
        # boundaries can leave a Live session receiving audio without producing a
        # response. The relay's 650 ms silence boundary is the single owner.
        # Screenshots and camera frames are tokenised at this resolution and then
        # stay in the session's context. 'medium' keeps on-screen text legible
        # for a fraction of a full-resolution frame.
        res = get_media_resolution()
        if res != "default":
            out["media_resolution"] = {
                "low":    types.MediaResolution.MEDIA_RESOLUTION_LOW,
                "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                "high":   types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            }[res]

        # Thinking is left at the server default deliberately. Forcing the budget
        # to zero was measured on gemini-3.1-flash-live over interleaved trials
        # and did not make the first word arrive sooner — this model does not
        # appear to deliberate on the Live path, so pinning the field only adds a
        # way for a future release to behave differently. Set "thinking_enabled"
        # in config/api_keys.json to true to let it reason instead.
        if get_thinking_enabled():
            out["thinking_config"] = types.ThinkingConfig(thinking_budget=-1)

        return out

    @staticmethod
    def _device_action_signature(device_id, capability, action_args):
        """Stable signature used to stop an unchanged rejected device action loop."""
        try:
            payload = json.dumps(action_args or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except Exception:
            payload = repr(action_args or {})
        return (str(device_id or ""), str(capability or "").strip().casefold(), payload)

    @staticmethod
    def _device_action_rejected(result):
        text = str(result or "").casefold()
        return any(marker in text for marker in (
            " rejected ", "rejected", "permission denied", "not permitted",
            "unsupported", "not supported", "device is offline", "failed:"
        ))

    def _guard_device_action(self, device_id, capability, action_args):
        sig = self._device_action_signature(device_id, capability, action_args)
        if self._blocked_device_action == sig:
            return sig, (
                "Blocked unchanged retry after the previous device action was rejected. "
                "Re-inspect the current device state and replan, or change the action/arguments before retrying."
            )
        return sig, None

    def _finish_device_action(self, sig, capability, result):
        cap = str(capability or "").strip().casefold()
        if self._device_action_rejected(result):
            self._blocked_device_action = sig
        elif cap in {"inspect", "android.ui.inspect", "ui.inspect", "screen.inspect"}:
            self._blocked_device_action = None
        elif self._blocked_device_action is not None and sig != self._blocked_device_action:
            # A different successful action changes the state/replan path, so the
            # previous rejection no longer needs to poison future legitimate work.
            self._blocked_device_action = None

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")


        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        if name != "task_continuity":
            task_state.action_started(name, args)
        _progress_task = None
        if name != "task_continuity":
            _progress_task = asyncio.create_task(self._tool_progress_heartbeat(name))

        try:
            if name == "self_repair_apply":
                if not str(args.get("plan_id", "")).strip() and self._last_repair_plan_id:
                    args["plan_id"] = self._last_repair_plan_id
                # Authorization must be grounded in the user's actual latest utterance.
                # Tool arguments are model-generated and therefore cannot prove human approval.
                _last_user = (self._current_user_transcript or next((x[5:].strip() for x in reversed(self._session_log) if x.startswith("User:")), ""))
                if not has_explicit_repair_apply_intent(_last_user):
                    result = ("Repair was not applied. Explicit user repair/apply approval is required in the latest request; "
                              "a model-generated authorization parameter is not sufficient.")
                    if _progress_task is not None:
                        _progress_task.cancel()
                        try:
                            await _progress_task
                        except asyncio.CancelledError:
                            pass
                    if not self.ui.muted:
                        self.ui.set_state("LISTENING")
                    task_state.action_finished(name, result)
                    return types.FunctionResponse(id=fc.id, name=name, response={"result": result})
                args["authorization"] = "APPLY_DIAGNOSTIC_REPAIR"
                if str(args.get("risk", "")).lower() == "high":
                    if not has_explicit_high_risk_approval(_last_user):
                        result = ("HIGH-risk repair was not applied. Ask the user to explicitly approve the high-risk repair; "
                                  "do not infer approval from a generic request to fix the issue.")
                        if _progress_task is not None:
                            _progress_task.cancel()
                            try:
                                await _progress_task
                            except asyncio.CancelledError:
                                pass
                        if not self.ui.muted:
                            self.ui.set_state("LISTENING")
                        task_state.action_finished(name, result)
                        return types.FunctionResponse(id=fc.id, name=name, response={"result": result})
                    args["high_risk_approval"] = "HIGH_RISK_REPAIR_APPROVED"

            if name == "self_repair_diagnostic":
                # Safety/UX gate: model routing alone must never turn a vague error
                # observation into a long diagnostic tool run.  Require explicit
                # diagnostic/repair intent in the user's actual latest utterance and
                # enough symptom detail to diagnose something concrete.
                _last_user = (self._current_user_transcript or next((x[5:].strip() for x in reversed(self._session_log) if x.startswith("User:")), ""))
                _intent = has_explicit_diagnostic_intent(_last_user)
                _generic = is_generic_error_report(_last_user)
                _problem = str(args.get("problem", "")).strip()
                _invented_generic = _problem.casefold() in {
                    "user noticed potential error and wants diagnosis",
                    "user noticed an error and wants diagnosis",
                    "potential error",
                }
                if not _intent or _generic or _invented_generic:
                    result = (
                        "Diagnostic was not started. The user has not yet provided explicit diagnostic intent "
                        "with a concrete symptom. Respond conversationally first: acknowledge the issue, ask what "
                        "failed or what they observed. Do not expose internal diagnostic safety-stage wording. Do not call this tool "
                        "again until the user explicitly asks to diagnose/check/debug/repair that concrete problem."
                    )
                else:
                    _ctx = {"player": self.ui, "speak": self.speak,
                            "response": None, "session_memory": None}
                    r = await loop.run_in_executor(None, lambda: self._action_registry.run(name, args, _ctx))
                    result = r or "Done."
                    _plan_match = re.search(r"^Repair plan:\s*([A-Za-z0-9-]+)\s*$", str(result), re.MULTILINE)
                    self._last_repair_plan_id = _plan_match.group(1) if _plan_match else ""
                    if self._last_repair_plan_id and has_explicit_repair_apply_intent(_last_user):
                        result += (
                            "\nNEXT ACTION: The current user request explicitly authorizes repair. "
                            "Call self_repair_apply now with apply=true and plan_id="
                            + self._last_repair_plan_id
                            + ". HIGH-risk still requires explicit high-risk approval."
                        )

                # Diagnostic is handled exactly once above. Returning here prevents
                # the generic action runner later in this method from executing it again.
                if _progress_task is not None:
                    _progress_task.cancel()
                    try:
                        await _progress_task
                    except asyncio.CancelledError:
                        pass
                task_state.action_finished(name, result)
                return types.FunctionResponse(id=fc.id, name=name, response={"result": result})

            elif name == "task_continuity":
                action = str(args.get("action", "")).strip().lower()
                if action == "begin":
                    goal = str(args.get("goal", "")).strip()
                    if not goal:
                        result = "A persistent task requires a non-empty goal."
                    else:
                        origin = self._dashboard.origin_device_id if self._dashboard else ""
                        task_state.begin(goal, str(args.get("constraints", "")),
                                         str(args.get("completion_criteria", "")), origin or "")
                        result = "Persistent task started."
                elif action == "checkpoint":
                    result = "Checkpoint saved." if task_state.checkpoint(str(args.get("summary", "")), str(args.get("evidence", ""))) else "No active persistent task."
                elif action == "block":
                    reason = str(args.get("reason", "")).strip()
                    _reason_lower = reason.casefold()
                    _credential_words = ("credential", "password", "passcode", "pin", "otp", "kata sandi", "kredensial")
                    _looks_credential = any(word in _reason_lower for word in _credential_words)
                    if _looks_credential:
                        _last = task_state.active().get("last_action") or {}
                        _last_text = json.dumps(_last, ensure_ascii=False).casefold()
                        _real_prompt = ("authentication_required" in _last_text
                                        or "credential input is blocked" in _last_text
                                        or "enter your password" in _last_text
                                        or "credential prompt" in _last_text)
                        if not _real_prompt:
                            result = ("Task was not paused for credentials: no actual credential prompt was observed. "
                                      "The preceding operation failed for another reason and must be routed or retried correctly.")
                        else:
                            result = "Task paused with blocker preserved." if task_state.block(reason) else "No active persistent task."
                    else:
                        result = "Task paused with blocker preserved." if task_state.block(reason) else "No active persistent task."
                elif action == "complete":
                    result = "Persistent task completed." if task_state.complete(str(args.get("evidence", ""))) else "No active persistent task."
                else:
                    result = "Unknown task continuity action."

            elif name == "current_datetime":
                now = datetime.now().astimezone()
                result = json.dumps({
                    "local_datetime": now.isoformat(timespec="seconds"),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M:%S"),
                    "weekday": now.strftime("%A"),
                    "timezone": now.tzname() or "local",
                }, ensure_ascii=False)

            elif name == "recall_memory":
                # Local file search: no network, no second model. Kept out of
                # the executor deliberately — it is a dictionary scan over a few
                # hundred short strings, and a thread hop would cost more than
                # the work itself.
                result = search_memory(args.get("query", ""), limit=8)

            elif name == "undo":
                if str(args.get("action", "")).lower().strip() == "list":
                    items = undo_stack.history()
                    result = ("Things I can undo, most recent first:\n"
                              + "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                              ) if items else "I have not changed anything I can undo yet."
                else:
                    result = await loop.run_in_executor(None, undo_stack.undo_last)

            elif name == "screen_process":
                # Companion-origin vision stays on the origin device.
                _origin = self._dashboard.origin_device_id if self._dashboard else None
                _last_user = (self._current_user_transcript or next((x[5:].strip() for x in reversed(self._session_log) if x.startswith("User:")), ""))
                _explicit_server = bool(re.search(
                    r"\b(?:on|from|using|use|via)\s+(?:the\s+)?(?:server|host)\b|"
                    r"\b(?:server|host)(?:'s)?\s+(?:camera|screen|display|webcam)\b",
                    _last_user, re.IGNORECASE,
                ))
                if _origin and not _explicit_server:
                    _rec = self._dashboard._mesh.get(_origin) or {}
                    _caps = set(_rec.get("capabilities") or [])
                    angle = str(args.get("angle", "screen")).strip().lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera" and "camera.capture" in _caps:
                        _facing = str(args.get("facing", "back")).strip().lower()
                        _reply = await self._dashboard.call_device(_origin, "camera.capture", {"facing": _facing})
                        if not isinstance(_reply, dict) or not _reply.get("ok", False):
                            result = str(_reply.get("result", _reply)) if isinstance(_reply, dict) else str(_reply)
                        else:
                            try:
                                _payload = json.loads(str(_reply.get("result", "")))
                                import base64 as _vision_b64
                                img_b = _vision_b64.b64decode(_payload["data"], validate=True)
                                mime_t = str(_payload.get("mime_type") or "image/jpeg")
                                if not img_b or not mime_t.startswith("image/"):
                                    raise ValueError("Companion returned invalid camera image data")
                                self._pending_vision = (self._session_generation, img_b, mime_t, user_text, "camera")
                                result = (
                                    f"[VISION_ACTIVE] {_payload.get('facing', _facing).capitalize()} camera frame captured "
                                    "and attached to this same exchange. Do not answer from UI text or memory; "
                                    "reply once from the attached image only."
                                )
                            except Exception as _vision_exc:
                                result = f"Camera capture failed validation: {_vision_exc}"
                    elif angle == "screen" and "screen.capture" in _caps:
                        _reply = await self._dashboard.call_device(_origin, "screen.capture", {})
                        if not isinstance(_reply, dict) or not _reply.get("ok", False):
                            result = str(_reply.get("result", _reply)) if isinstance(_reply, dict) else str(_reply)
                        else:
                            try:
                                _payload = json.loads(str(_reply.get("result", "")))
                                import base64 as _vision_b64
                                img_b = _vision_b64.b64decode(_payload["data"], validate=True)
                                mime_t = str(_payload.get("mime_type") or "image/jpeg")
                                if not img_b or not mime_t.startswith("image/"):
                                    raise ValueError("Companion returned invalid screen image data")
                                self._pending_vision = (self._session_generation, img_b, mime_t, user_text, "screen")
                                result = ("[VISION_ACTIVE] Origin desktop screen captured and attached to this exchange. "
                                          "Wait for the image and answer from its contents only.")
                            except Exception as _vision_exc:
                                result = f"Screen capture failed validation: {_vision_exc}"
                    elif angle == "camera":
                        result = "This companion does not advertise camera.capture. A real image frame is required; UI inspection cannot substitute for camera vision."
                    else:
                        result = "This companion does not advertise a real screen-capture capability. UI inspection cannot substitute for visual screen analysis."
                elif _explicit_server:
                    result = (
                        "The server is headless and does not expose local screen/camera hardware. "
                        "Use a paired companion that advertises screen.capture or camera.capture."
                    )
                else:
                    result = (
                        "No companion origin is associated with this vision request. "
                        "Server camera/screen capture is not a fallback; request server/host hardware explicitly if that is intended."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "list_paired_devices":
                if not self._dashboard:
                    result = "Device mesh is unavailable."
                else:
                    devices = self._dashboard._mesh.list_devices()
                    online = set(self._dashboard._device_sockets)
                    for d in devices: d["online"] = d.get("device_id") in online
                    result = json.dumps(devices, ensure_ascii=False) if devices else "No paired devices."

            elif name == "transfer_file":
                if not self._dashboard:
                    result = "Device mesh is unavailable."
                else:
                    devices=self._dashboard._mesh.list_devices(); online=set(self._dashboard._device_sockets)
                    def _resolve(sel):
                        sel=str(sel or "").strip(); exact=next((d for d in devices if d.get("device_id")==sel),None)
                        if exact:return exact
                        matches=[d for d in devices if str(d.get("name","")).casefold()==sel.casefold() and not d.get("revoked")]
                        if len(matches)==1:return matches[0]
                        online_matches=[d for d in matches if d.get("device_id") in online]
                        return online_matches[0] if len(online_matches)==1 else None
                    source_selector=str(args.get("source_device") or "").strip()
                    target_selector=str(args.get("destination_device") or "").strip()
                    src=(_resolve(self._dashboard.origin_device_id) if source_selector.casefold() in ("current", "this device", "this phone") else _resolve(source_selector))
                    dst=({"device_id":"server","capabilities":[]} if target_selector.casefold() == "server" else _resolve(target_selector))
                    if self._attachment_turn and self._dashboard.attachment_request_status(str(self._attachment_turn.get("request_id") or "")):
                        result=json.dumps(self._dashboard.attachment_request_status(str(self._attachment_turn["request_id"])),ensure_ascii=False)
                    elif not src or not dst: result="Source or destination companion is not uniquely identifiable. Call list_paired_devices first."
                    elif src.get("device_id")==dst.get("device_id"): result="Source and destination are the same companion. For server storage use destination_device=server; otherwise choose a different paired device."
                    elif src.get("device_id") not in online: result="Source companion is offline; it must be online to attach a local file."
                    elif "file.upload" not in set(src.get("capabilities") or []): result="Source companion does not support file.upload."
                    elif dst.get("device_id")!="server" and "attachment.inbox" not in set(dst.get("capabilities") or []): result="Destination companion does not support attachment.inbox."
                    else:
                        src_id=str(src["device_id"]); dst_id=str(dst["device_id"])
                        active=self._attachment_turn
                        if active and active.get("source_device")==src_id and active.get("destination_device")==dst_id:
                            # A native picker owns this logical transfer. Ignore model retries,
                            # including invented content:// URIs, until the next real user turn.
                            known=self._dashboard.attachment_request_status(str(active.get("request_id") or ""))
                            if known and known.get("status") in ("completed","partial","failed","cancelled"):
                                result=json.dumps(known,ensure_ascii=False)
                            else:
                                result=json.dumps({"ok":True,"status":"already_in_progress","request_id":active.get("request_id"),
                                    "message":"The attachment request is already in progress. Do not call transfer_file again in this user turn."},ensure_ascii=False)
                        else:
                            info=await self._dashboard.transfer_file(src_id,dst_id,str(args.get("source") or ""),str(args.get("destination_name") or ""),bool(args.get("keep_on_server",False)))
                            if info.get("status")=="awaiting_selection":
                                self._attachment_turn={"source_device":src_id,"destination_device":dst_id,"request_id":info.get("request_id")}
                            result=json.dumps(info,ensure_ascii=False)

            elif name == "send_server_file":
                if not self._dashboard:
                    result = "Device mesh is unavailable."
                else:
                    devices=self._dashboard._mesh.list_devices(); online=set(self._dashboard._device_sockets)
                    selector=str(args.get("destination_device") or "").strip()
                    if selector.casefold() in ("current", "this device", "this phone"):
                        target=self._dashboard._mesh.get(self._dashboard.origin_device_id) or {}
                    else:
                        exact=next((d for d in devices if d.get("device_id")==selector and not d.get("revoked")),None)
                        matches=[d for d in devices if str(d.get("name","")).casefold()==selector.casefold() and not d.get("revoked")]
                        target=exact or (matches[0] if len(matches)==1 else None)
                    save_direct=bool(args.get("save_direct",False))
                    required_capability="file.receive" if save_direct else "attachment.inbox"
                    if not target:
                        result="Destination companion is not uniquely identifiable. Call list_paired_devices first."
                    elif required_capability not in set(target.get("capabilities") or []):
                        result=f"Destination companion does not support {required_capability}."
                    elif save_direct and target.get("device_id") not in online:
                        result="Destination companion is offline; direct saving requires it to be online. Use normal attachment delivery instead."
                    else:
                        result=json.dumps(await self._dashboard.send_server_file(
                            str(target["device_id"]), str(args.get("source") or ""),
                            str(args.get("destination_name") or ""),
                            save_direct=save_direct, destination=str(args.get("destination") or "")), ensure_ascii=False)

            elif name == "call_current_device":
                if not self._dashboard:
                    result = "Device mesh is unavailable."
                else:
                    device_id = self._dashboard.origin_device_id
                    if not device_id:
                        result = "No active companion device is associated with this request."
                    else:
                        _requested_cap = str(args.get("capability", "")).strip()
                        _rec = self._dashboard._mesh.get(device_id) or {}
                        _caps = set(_rec.get("capabilities") or [])
                        _generic_aliases = {
                            "inspect": "android.ui.inspect",
                            "click": "android.ui.click",
                            "text": "android.ui.text",
                            "scroll": "android.ui.scroll",
                            "global": "android.ui.global",
                        }
                        _mapped_cap = _generic_aliases.get(_requested_cap.lower(), _requested_cap)
                        if _mapped_cap != _requested_cap and _mapped_cap not in _caps:
                            _mapped_cap = _requested_cap
                        _device_args = args.get("args") or {}
                        if _mapped_cap == "legacy.action" and not str(_device_args.get("tool") or "").strip():
                            result = "legacy.action requires a named desktop tool and its parameters."
                        elif _mapped_cap not in _caps:
                            result = (f"The current companion does not permit {_mapped_cap}. "
                                      "Check its advertised capabilities and required device permissions "
                                      "before trying a different supported action.")
                        else:
                            _sig, _blocked = self._guard_device_action(device_id, _mapped_cap, _device_args)
                            if _blocked:
                                result = _blocked
                            else:
                                try:
                                    reply = await self._dashboard.call_device(device_id, _mapped_cap, _device_args)
                                except PermissionError:
                                    result = (f"The current companion rejected {_mapped_cap}. "
                                              "Check its device permission or re-pair if capability grants changed.")
                                else:
                                    result = str(reply.get("result", reply)) if isinstance(reply, dict) else str(reply)
                                    self._finish_device_action(_sig, _mapped_cap, result)

            elif name == "call_paired_device":
                if not self._dashboard:
                    result = "Device mesh is unavailable."
                else:
                    selector = str(args.get("device_id", "")).strip()
                    devices = self._dashboard._mesh.list_devices()
                    online = set(self._dashboard._device_sockets)
                    target = next((d for d in devices if d.get("device_id") == selector), None)
                    if target is None:
                        # Device names are human labels and may be duplicated after a
                        # re-pair. Prefer the currently connected record so an older
                        # offline record with the same phone name cannot shadow it.
                        name_matches = [d for d in devices if str(d.get("name", "")).casefold() == selector.casefold()]
                        target = next((d for d in name_matches if d.get("device_id") in online), None)
                        if target is None and len(name_matches) == 1:
                            target = name_matches[0]
                    # Older model turns sometimes used the visible list position ("1")
                    # instead of the opaque device id. Resolve that safely only against
                    # the current online paired-device list; never treat it as an id.
                    if target is None and selector.isdigit():
                        candidates = [d for d in devices if d.get("device_id") in online]
                        pos = int(selector) - 1
                        if 0 <= pos < len(candidates):
                            target = candidates[pos]
                    if target is None:
                        result = f"Paired device {selector!r} was not found. Call list_paired_devices and use its exact device_id or name."
                    else:
                        _target_id = str(target.get("device_id"))
                        _capability = str(args.get("capability", ""))
                        _device_args = args.get("args") or {}
                        _caps = set(target.get("capabilities") or [])
                        if _capability == "legacy.action" and not str(_device_args.get("tool") or "").strip():
                            result = "legacy.action requires a named desktop tool and its parameters."
                        elif not _capability or _capability not in _caps:
                            result = (f"Paired device {_target_id} does not permit {_capability or 'an unspecified capability'}. "
                                      "Check its advertised capabilities and required device permissions.")
                        else:
                            _sig, _blocked = self._guard_device_action(_target_id, _capability, _device_args)
                            if _blocked:
                                result = _blocked
                            else:
                                try:
                                    reply = await self._dashboard.call_device(_target_id, _capability, _device_args)
                                except PermissionError:
                                    result = (f"Paired device {_target_id} rejected {_capability}. "
                                              "Check its device permission or re-pair if capability grants changed.")
                                else:
                                    result = str(reply.get("result", reply)) if isinstance(reply, dict) else str(reply)
                                    self._finish_device_action(_sig, _capability, result)

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                async def _do_shutdown():
                    await self._save_session_summary()
                    if self.session:
                        try:
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": "Say a brief natural goodbye to the user."}]},
                                turn_complete=True,
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(1.5)
                    import os as _os
                    _os._exit(0)
                asyncio.create_task(_do_shutdown())

            elif self._action_registry.has(name):
                # Origin-first execution guard.  A tool chosen from actions/* is a
                # server-local implementation, but a request arriving from a companion
                # means "this device" unless the user explicitly said server/host.
                # Enforce that in code instead of trusting the model to always choose
                # call_current_device.  Desktop companions can run the established
                # legacy actions locally; Android app launches map to app.launch.
                _origin = self._dashboard.origin_device_id if self._dashboard else None
                _last_user = (self._current_user_transcript or next((x[5:].strip() for x in reversed(self._session_log) if x.startswith("User:")), ""))
                _explicit_server = bool(re.search(r"\b(server|host)\b", _last_user, re.IGNORECASE))
                _device_local_actions = {
                    "open_app", "computer_control", "computer_settings", "desktop_control",
                    "file_controller", "browser_control", "screen_processor", "send_message",
                    "system_monitor", "youtube_video", "video_player",
                }
                # These actions are server-side work. Never reinterpret them as
                # Android/Desktop UI operations merely because the request arrived
                # through a companion; device work must use call_current_device or
                # legacy.action explicitly.
                _server_only_actions = {"code_helper", "dev_agent", "web_search", "self_repair_diagnostic", "self_repair_apply"}

                # Mixed actions can contain both backend-only operations and operations that
                # manipulate a device/host UI.  Classify the requested operation instead of
                # blocking the entire action whenever a request originates from a companion.
                _generic_device_operations = {
                    "open", "open_app", "open_file", "open_editor", "launch", "close",
                    "show", "display", "preview", "focus", "select", "choose",
                    "click", "tap", "press", "hotkey", "type", "write", "insert",
                    "scroll", "swipe", "back", "home", "search_ui", "navigate_ui",
                    "install", "update", "patch", "restart", "print",
                }

                _mixed_device_action_ops = {
                    "code_helper": {
                        "open", "open_editor", "launch", "type", "write", "insert",
                        "click", "press", "hotkey", "focus", "close",
                    },
                    "game_updater": {
                        "open", "launch", "install", "update", "patch", "click",
                        "type", "press", "close", "restart",
                    },
                    "file_processor": {
                        "open", "open_file", "launch", "show", "preview", "print",
                        "click", "type", "press",
                    },
                }

                def _requested_operation(tool_args):
                    if not isinstance(tool_args, dict):
                        return ""
                    for key in ("action", "operation", "command", "mode"):
                        value = tool_args.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip().lower()
                    return ""

                def _is_companion_device_operation(tool_name, tool_args):
                    """Return True only when a mixed action requests device-local execution."""
                    if tool_name in _device_local_actions:
                        return True
                    operation = _requested_operation(tool_args)
                    return operation in _generic_device_operations or operation in _mixed_device_action_ops.get(tool_name, set())

                if (_origin and name not in _server_only_actions
                        and _is_companion_device_operation(name, args)
                        and not _explicit_server):
                    try:
                        _rec = self._dashboard._mesh.get(_origin) or {}
                        _caps = set(_rec.get("capabilities") or [])
                        if name == "open_app" and "app.launch" in _caps:
                            _app = args.get("app_name") or args.get("app") or args.get("name") or ""
                            _reply = await self._dashboard.call_device(_origin, "app.launch", {"app": _app})
                            result = str(_reply.get("result", _reply)) if isinstance(_reply, dict) else str(_reply)
                        elif "legacy.action" in _caps:
                            _reply = await self._dashboard.call_device(
                                _origin, "legacy.action", {"tool": name, "parameters": args}
                            )
                            result = str(_reply.get("result", _reply)) if isinstance(_reply, dict) else str(_reply)
                        else:
                            # Do not silently fall through and execute the action on the
                            # server.  Tell the model which current-device path to use so
                            # Android UI workflows can continue through inspect/act/verify.
                            result = (
                                f"Origin companion {_origin} does not expose a direct mapping for server-local tool {name}. "
                                "Do not run it on the server. Continue on the current companion with call_current_device "
                                "and its advertised generic inspect/act capabilities. Re-inspect after each action and verify the requested end state."
                            )
                    except Exception as _route_error:
                        result = f"Origin-device routing failed: {_route_error}"
                else:
                    # file_processor: fall back to the currently-uploaded file when none is given
                    if name == "file_processor" and not args.get("file_path") and self.ui.current_file:
                        args["file_path"] = self.ui.current_file
                    _ctx = {"player": self.ui, "speak": self.speak,
                            "response": None, "session_memory": None}
                    r = await loop.run_in_executor(None, lambda: self._action_registry.run(name, args, _ctx))
                    result = r or "Done."
                    if name == "self_repair_diagnostic":
                        _plan_match = re.search(r"^Repair plan:\s*([A-Za-z0-9-]+)\s*$", str(result), re.MULTILINE)
                        self._last_repair_plan_id = _plan_match.group(1) if _plan_match else ""
                        if self._last_repair_plan_id and has_explicit_repair_apply_intent(_last_user):
                            result += (
                                "\nNEXT ACTION: The user's current utterance already explicitly authorizes repair. "
                                "Call self_repair_apply now with apply=true and plan_id="
                                + self._last_repair_plan_id
                                + ". Do not stop at the read-only diagnosis. HIGH-risk still requires explicit high-risk approval."
                            )
                    # web_search: mirror results to the on-screen content panel
                    if (name == "web_search" and r
                            and not r.startswith("No results")
                            and not r.startswith("Search failed")):
                        _mode  = args.get("mode", "search")
                        _query = args.get("query") or ", ".join(args.get("items", []))
                        _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                        self.ui.show_content(_label, r)


            else:
                if self._plugin_registry.has(name):
                    r = await loop.run_in_executor(
                        None,
                        lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if _progress_task is not None:
            _progress_task.cancel()
            try:
                await _progress_task
            except asyncio.CancelledError:
                pass
        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")

        # A tool that declared itself NON_BLOCKING also says when its answer may
        # re-enter the conversation. Without this the model finishes whatever it
        # was saying and then reads the result out on top of it — which, for
        # something like a phone call already ringing, is exactly the noise the
        # non-blocking call was meant to avoid. Tools that declared nothing get
        # the API default and behave as they always have.
        _sched = (self._action_registry.scheduling(name)
                  or self._plugin_registry.scheduling(name))
        _extra = {"scheduling": _sched} if _sched else {}
        if name != "task_continuity":
            task_state.action_finished(name, result)
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result},
            **_extra
        )

    def _note_live_progress(self) -> None:
        """Record meaningful provider progress and clear stale voice deadlines."""
        self._live_progress_seq += 1
        self._pending_voice_turns.clear()
        self._unanswered_voice_turns = 0

    def _note_voice_activity_start(self) -> None:
        # A fresh user utterance is a new turn. Do not let an interrupted prior
        # answer poison all future response audio if Gemini omitted turn_complete.
        self._interrupted = False
        # Provider/tool replay inside one turn must never repeat side effects.
        # A genuinely new user turn may legitimately request the same action again.
        self._tool_turn_cache.clear()
        self._voice_turn_seq += 1

    def _note_voice_activity_end(self) -> None:
        self._pending_voice_turns.append((
            self._voice_turn_seq,
            time.monotonic() + self._live_stall_timeout,
            self._live_progress_seq,
        ))
        # Bound state even if a noisy microphone creates many boundaries.
        if len(self._pending_voice_turns) > 8:
            self._pending_voice_turns = self._pending_voice_turns[-8:]

    async def _watch_live_stall(self) -> None:
        """Recover an open-but-silent Gemini Live session.

        One unanswered activity boundary can be noise or an utterance for which
        no answer is appropriate. Two consecutive ended voice turns with no
        meaningful provider content indicate the failure seen in interaction.log:
        PCM continues to send successfully while Gemini produces nothing and no
        exception reaches error.log.
        """
        while True:
            await asyncio.sleep(0.5)
            if not self._pending_voice_turns:
                continue
            now = time.monotonic()
            expired = [x for x in self._pending_voice_turns if x[1] <= now]
            if not expired:
                continue
            self._pending_voice_turns = [x for x in self._pending_voice_turns if x[1] > now]
            for turn_seq, _deadline, progress_seq in expired:
                if progress_seq != self._live_progress_seq:
                    continue
                self._unanswered_voice_turns += 1
                _trace_event(
                    "live_silent_turn",
                    turn=turn_seq,
                    consecutive=self._unanswered_voice_turns,
                )
                if self._unanswered_voice_turns >= 2:
                    _trace_event("live_stall_reconnect", turn=turn_seq)
                    self._reconnect_keep = True
                    self._reconnect_reason = "silent Live session recovery"
                    if self._reconnect_event:
                        self._reconnect_event.set()
                    return

    async def _send_realtime(self):
        sent = 0
        while True:
            msg = await self.out_queue.get()
            if msg.get("activity_start"):
                await self.session.send_realtime_input(activity_start=types.ActivityStart())
                self._note_voice_activity_start()
                _trace_event("activity_start")
                continue
            if msg.get("activity_end"):
                await self.session.send_realtime_input(activity_end=types.ActivityEnd())
                self._note_voice_activity_end()
                _trace_event("activity_end")
                continue
            # Gemini 3.x Live rejects the old realtime_input.media_chunks field
            # (what `media=...` maps to) and closes the socket with a 1007. Send
            # mic / phone PCM through the new `audio` field instead. Queue items
            # are {"data": <bytes>, "mime_type": <str>} from _listen_audio and
            # the phone relay.
            await self.session.send_realtime_input(
                audio=types.Blob(
                    data=msg["data"],
                    mime_type=msg.get("mime_type", "audio/pcm"),
                )
            )
            sent += 1
            if sent == 1 or sent % 50 == 0:
                _trace_event("audio_to_gemini", chunks=sent, bytes=len(msg.get("data", b"")))

    async def _listen_audio(self):
        """Server runtime never opens a local microphone.

        All interactive audio must arrive from an authenticated native companion
        through the device mesh.  Keeping this task alive preserves the existing
        Gemini Live task topology without touching host audio hardware.
        """
        print("[SERVER] Local microphone disabled; waiting for companion audio.")
        while True:
            await asyncio.sleep(3600)

    async def _flush_pending_vision(self) -> bool:
        """Send a captured frame immediately after its tool response.

        The frame is already in hand by the time `screen_process` returns — the
        capture happened inside the tool call. The old flow still made the model
        speak a turn first and only injected the image on that turn's
        turn_complete, which cost a whole extra round trip AND produced two
        spoken answers: one improvised without the picture, then the real one.
        Sending it here means the model has the tool result and the image before
        it generates anything, so the user gets one answer, sooner.
        """
        if not (self._pending_vision and self.session):
            return False

        import base64 as _b64
        generation, img_b, mime_t, question, angle = self._pending_vision
        self._pending_vision = None

        # A frame belongs to exactly one Live connection.  Never replay bytes
        # captured for a session that has already rolled over/reconnected.
        if generation != self._session_generation:
            self._vision_busy = False
            print("[Vision] Dropped stale frame from a previous Live session")
            return False
        if not isinstance(img_b, (bytes, bytearray)) or not img_b:
            self._vision_busy = False
            print("[Vision] Dropped empty/invalid image payload")
            return False
        mime_t = str(mime_t or "").strip().lower()
        if mime_t not in {"image/jpeg", "image/png", "image/webp"}:
            self._vision_busy = False
            print(f"[Vision] Dropped unsupported image MIME: {mime_t!r}")
            return False
        if len(img_b) > 20 * 1024 * 1024:
            self._vision_busy = False
            print(f"[Vision] Dropped oversized image payload: {len(img_b):,} bytes")
            return False
        b64 = _b64.b64encode(bytes(img_b)).decode("ascii")
        print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}, session={generation}) → main session")

        # Label the source. Without it the image arrives carrying nothing but
        # the user's own sentence, and a screenshot of this app — which has a
        # face in the middle of it — got read as a photo of the user. What the
        # label *means* is explained once, in the generated [SELF] block.
        src = ("[IMAGE SOURCE: WEBCAM]" if angle == "camera"
               else "[IMAGE SOURCE: SCREEN CAPTURE]")
        await self.session.send_client_content(
            turns={"role": "user", "parts": [
                {"inline_data": {"mime_type": mime_t, "data": b64}},
                {"text": f"{src}\n\n{question}"},
            ]},
            turn_complete=True,
        )

        if self._vision_cam_active:
            # Camera: stay busy until JARVIS has finished speaking the answer,
            # then close the preview.
            self._vision_cam_active    = False
            self._vision_close_pending = True
        else:
            self._vision_busy = False
        return True

    def _broadcast_transcript_delta(self, speaker: str, text: str) -> None:
        text = _clean_transcript(text)
        if not text or not self._dashboard:
            return
        asyncio.create_task(self._dashboard.broadcast({
            "type": "transcript.delta",
            "speaker": speaker,
            "text": text,
            "final": False,
            "ts": datetime.now().isoformat(),
        }))

    def _record_transcript_entry(self, speaker: str, text: str, partial: bool = False) -> None:
        text = _clean_transcript(text)
        if not text:
            return
        label = f"{self._asst_name} [partial]" if speaker == "jarvis" and partial else ("You [partial]" if speaker == "user" and partial else (self._asst_name if speaker == "jarvis" else "You"))
        self.ui.write_log(f"{label}: {text}")
        self._session_log.append(f"{label}: {text}")
        if self._dashboard:
            asyncio.create_task(self._dashboard.broadcast({
                "type": "log",
                "speaker": speaker,
                "text": text,
                "partial": partial,
                "ts": datetime.now().isoformat(),
            }))

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():
                    if response.data or response.server_content or response.tool_call:
                        self._note_live_progress()

                    # ── Session resumption ───────────────────────────────────
                    # The server sends this periodically. `resumable` goes false
                    # while a turn is mid-flight — replaying a handle from that
                    # moment is what the flag exists to prevent — so only
                    # resumable handles are kept. This is three lines and it is
                    # the entire fix for "every reconnect forgets everything".
                    _sru = getattr(response, "session_resumption_update", None)
                    if _sru is not None:
                        if getattr(_sru, "resumable", False) and getattr(_sru, "new_handle", None):
                            if self._resume_handle is None:
                                print("[JARVIS] 🔗 Session resumption armed")
                            self._resume_handle = _sru.new_handle

                    if response.data:
                        if self._interrupted:
                            pass  # discard: interrupted
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        # THINKING is event-driven, not timer-driven: publish it only
                        # when Gemini has started producing server-side turn content
                        # but response audio has not started yet.
                        if not response.data and not self._is_speaking:
                            _has_model_content = bool(
                                (sc.output_transcription and sc.output_transcription.text)
                                or getattr(sc, "model_turn", None)
                            )
                            if _has_model_content:
                                self.set_thinking()

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            # A turn that involves a tool call passes through
                            # several turn_completes, and the API re-sends the
                            # tail of the transcript across them. Comparing only
                            # against the previous chunk missed that — once
                            # out_buf had been flushed and emptied, the repeat
                            # sailed straight back in, which logged the answer
                            # twice AND made the avatar mouth it twice.
                            if txt and not _is_repeat_chunk(txt, out_buf):
                                out_buf.append(txt)
                                self._broadcast_transcript_delta("jarvis", " ".join(out_buf))
                                # Hand the words to the mouth as they arrive, so
                                # the avatar can form the consonants the audio
                                # alone cannot show. Pure string work — it adds
                                # nothing measurable to the response path.
                                self._visemes.feed_text(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                if not in_buf:
                                    # New voice input arrives before its tool calls.
                                    self._attachment_turn = None
                                    self._blocked_device_action = None
                                in_buf.append(txt)
                                self._current_user_transcript = " ".join(in_buf).strip()
                                self._broadcast_transcript_delta("user", self._current_user_transcript)
                                self._last_user_speech = time.monotonic()

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # An interrupted response may still contain the user's
                            # input transcription. Preserve that input in the local
                            # conversation/session history; only the unfinished
                            # assistant output is discarded. This keeps a follow-up
                            # such as "make it at least 10 pages" attached to the
                            # preceding request instead of turning it into contextless
                            # audio after the interrupt.
                            if self._interrupted:
                                interrupted_out = " ".join(out_buf).strip()
                                if interrupted_out:
                                    # Preserve words already transcribed/displayed. Interruption
                                    # stops future audio; it must not erase visible conversation.
                                    self._record_transcript_entry("jarvis", interrupted_out, partial=True)
                                interrupted_in = " ".join(in_buf).strip()
                                if interrupted_in:
                                    self._last_out_logged = ""
                                    self.ui.write_log(f"You: {interrupted_in}")
                                    self._session_log.append(f"User: {interrupted_in}")
                                    if self._dashboard:
                                        asyncio.create_task(self._dashboard.broadcast({
                                            "type": "log", "speaker": "user",
                                            "text": interrupted_in,
                                            "ts": datetime.now().isoformat(),
                                            "interrupted": True,
                                        }))
                                self._interrupted = False
                                self._current_user_transcript = ""
                                in_buf = []
                                out_buf = []
                                self._visemes.reset()
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self._last_out_logged = ""   # new exchange
                                self.ui.write_log(f"You: {full_in}")
                                self._session_log.append(f"User: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            self._current_user_transcript = ""
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            # Second line of defence: even if a repeat slips
                            # into a *fresh* buffer after a flush, never log the
                            # same answer (or a tail of it) twice in a row.
                            if full_out and len(full_out) >= _REPEAT_MIN and self._last_out_logged:
                                if full_out in self._last_out_logged:
                                    full_out = ""
                            if full_out:
                                self._last_out_logged = full_out
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            out_buf = []

                            if self._vision_close_pending:
                                # This turn_complete IS the vision answer — close camera + release busy flag
                                self._vision_close_pending = False
                                self._vision_busy = False
                                async def _cam_close():
                                    await asyncio.sleep(2.0)
                                    self.ui.stop_camera_stream()
                                asyncio.create_task(_cam_close())

                    if response.tool_call:
                        # Tool execution is also genuine processing time before the
                        # spoken answer, so expose it as THINKING on companions.
                        self.set_thinking()
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            try:
                                _tool_payload = json.dumps(dict(fc.args or {}), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                            except Exception:
                                _tool_payload = repr(dict(fc.args or {}))
                            _tool_sig = (str(fc.name), _tool_payload)
                            _cached = self._tool_turn_cache.get(_tool_sig)
                            if _cached is not None:
                                _trace_event("tool_duplicate_suppressed", tool=str(fc.name))
                                fr = types.FunctionResponse(id=fc.id, name=fc.name, response=_cached)
                            else:
                                fr = await self._execute_tool(fc)
                                _response_payload = getattr(fr, "response", None)
                                if isinstance(_response_payload, dict):
                                    self._tool_turn_cache[_tool_sig] = dict(_response_payload)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
                        await self._flush_pending_vision()
        except Exception as e:
            # Preserve the visible/input text even when the provider closes before
            # turn_complete. The next session can continue from an explicit partial
            # entry instead of silently losing the current turn.
            for speaker, text in _partial_transcript_entries(in_buf, out_buf, self._asst_name):
                self._record_transcript_entry(speaker, text, partial=True)
            if self._dashboard:
                self._dashboard.set_phone_audio_enabled(False)
            # The receive task sees normal Gemini Live session rollover first.
            # Let run() classify/reconnect it, but do not dump a traceback here;
            # otherwise an expected 1008/GoAway/transport rollover is printed
            # before the outer lifecycle handler can recognise it.
            _recv_err = _exception_text(e).lower()
            _expected_rollover = (
                "goaway" in _recv_err
                or "session durat" in _recv_err
                or ("1008" in _recv_err and (
                    "failed to close" in _recv_err
                    or "operation was aborted" in _recv_err
                ))
                or "keepalive ping timeout" in _recv_err
                or "timed out while closing connection" in _recv_err
                or _is_transient_transport_error(e)
            )
            if not _expected_rollover:
                print(f"[JARVIS] ❌ Recv: {e}")
                traceback.print_exc()
            raise

    async def _play_audio(self):
        """Relay model PCM only to the companion that owns the live interaction.

        The server deliberately has no speaker output.  This prevents a headless
        host from speaking when Android/desktop companion is the active surface.
        """
        print("[SERVER] Local speaker disabled; companion audio relay active.")
        while True:
            try:
                chunk = await asyncio.wait_for(self.audio_in_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                if self._turn_done_event and self._turn_done_event.is_set() and self.audio_in_queue.empty():
                    self.set_speaking(False)
                    self._turn_done_event.clear()
                    # Picker/UI continuations must wait for the completed Live turn,
                    # not merely a transient SPEAKING -> LISTENING audio transition.
                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "assistant.turn.complete"})
                continue
            self.set_speaking(True)
            batch = bytearray(chunk)
            while len(batch) < 9600:
                try:
                    batch.extend(self.audio_in_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if self._dashboard:
                try:
                    # Keep relay cadence close to 24 kHz mono PCM real time. The
                    # provider often returns a large burst; sending that burst
                    # immediately makes the companion queue underrun later.
                    if len(batch) & 1:
                        batch = batch[:-1]
                    if not batch:
                        continue
                    now = time.monotonic()
                    if self._audio_relay_cursor < now:
                        self._audio_relay_cursor = now
                    await asyncio.sleep(max(0.0, self._audio_relay_cursor - now))
                    await self._dashboard.send_device_audio(bytes(batch))
                    self._audio_relay_cursor += len(batch) / 48_000.0
                except Exception as exc:
                    print(f"[SERVER] companion audio relay error: {exc}")

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to long_term.json."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []    # reset immediately so the next session starts clean

        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = lang or "English"

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from core import gemini
            summary = await asyncio.to_thread(
                gemini.text, prompt, gemini.SMART, None, 30_000,
            )
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session or not self._awake:
                continue
            # Don't interrupt an active conversation
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": alert}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session and self._awake:
                # Don't interrupt if user spoke recently or JARVIS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "English"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            print("[JARVIS] Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session or not self._awake:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                )
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                print("[JARVIS] Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _classify_barge_in(self, pcm: bytes) -> None:
        """Classify a full-duplex speech candidate by meaning, not language.

        Fail closed: if classification is unavailable or ambiguous, playback is
        not interrupted. The audio itself is never written to logs.
        """
        if not pcm or self._barge_classifying:
            return
        self._barge_classifying = True
        try:
            prompt = (
                "Classify the intent of this speech heard while an assistant is currently speaking. "
                "Understand ANY human language. Return exactly one token: INTERRUPT if the speaker "
                "means stop, wait, pause, cancel, objects/corrects the assistant, or deliberately "
                "takes the conversational turn; IGNORE for background conversation, TV/media, echo, "
                "incidental speech, acknowledgements that do not request the floor, or ambiguous audio. "
                "When uncertain return IGNORE."
            )
            part = types.Part.from_bytes(data=pcm, mime_type="audio/pcm;rate=16000")
            verdict = await asyncio.to_thread(
                _gemini.text, [part, prompt], _gemini.FAST, None, 10_000, "", "IGNORE"
            )
            verdict = (verdict or "IGNORE").strip().upper()
            accepted = verdict == "INTERRUPT"
            _trace_event("barge_semantic_decision", accepted=accepted)
            if not accepted or not self.session or not self.out_queue:
                return
            self.interrupt()
            # Replay the accepted utterance into the interactive Live session so
            # the correction/request is understood rather than merely stopping audio.
            await self.out_queue.put({"activity_start": True})
            for i in range(0, len(pcm), CHUNK_SIZE):
                await self.out_queue.put({
                    "data": pcm[i:i + CHUNK_SIZE],
                    "mime_type": "audio/pcm;rate=16000",
                })
            await self.out_queue.put({"activity_end": True})
        except Exception as exc:
            _trace_event("barge_semantic_unavailable", error=type(exc).__name__)
        finally:
            self._barge_classifying = False

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM; speaking-time audio is a semantic barge candidate."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                self._phone_active = False
                with self._speaking_lock:
                    speaking = self._is_speaking
                if speaking and self._barge_voice_active and time.monotonic() - self._barge_last_voice >= 0.65:
                    pcm = bytes(self._barge_audio)
                    self._barge_audio.clear()
                    self._barge_voice_active = False
                    if pcm and not self._barge_classifying:
                        asyncio.create_task(self._classify_barge_in(pcm))
                elif not speaking and self._phone_activity_active and time.monotonic() - self._phone_last_voice >= 0.65:
                    try:
                        self.out_queue.put_nowait({"activity_end": True})
                    except asyncio.QueueFull:
                        pass
                    self._phone_activity_active = False
                continue

            self._phone_active = True
            raw = chunk.get("data", b"")
            try:
                samples = np.frombuffer(raw, dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0
            except Exception:
                rms = 0.0
            now = time.monotonic()
            voice = rms >= 250.0
            with self._speaking_lock:
                speaking = self._is_speaking

            if speaking:
                # Do not send activity boundaries without their PCM. That old
                # behaviour could disturb Live turn state while giving Gemini no
                # words from which to decide whether the user meant to interrupt.
                if voice:
                    self._barge_last_voice = now
                    self._barge_voice_active = True
                if self._barge_voice_active and len(self._barge_audio) < self._barge_max_bytes:
                    remaining = self._barge_max_bytes - len(self._barge_audio)
                    self._barge_audio.extend(raw[:remaining])
                if self._barge_voice_active and not voice and now - self._barge_last_voice >= 0.65:
                    pcm = bytes(self._barge_audio)
                    self._barge_audio.clear()
                    self._barge_voice_active = False
                    if pcm and not self._barge_classifying:
                        asyncio.create_task(self._classify_barge_in(pcm))
                continue

            # Normal listening path. Drop any stale speaking-time candidate when
            # playback ended naturally before classification completed.
            if self._barge_voice_active:
                self._barge_audio.clear()
                self._barge_voice_active = False
            if voice:
                self._phone_last_voice = now
                if not self._phone_activity_active:
                    try:
                        self.out_queue.put_nowait({"activity_start": True})
                    except asyncio.QueueFull:
                        pass
                    self._phone_activity_active = True
            elif self._phone_activity_active and now - self._phone_last_voice >= 0.65:
                try:
                    self.out_queue.put_nowait({"activity_end": True})
                except asyncio.QueueFull:
                    pass
                self._phone_activity_active = False
            if not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    async def _run_scheduled_workflows(self) -> None:
        """Execute only schedules explicitly created by the user.

        The persisted last_run_date is claimed before execution, so Live-session
        reconnects cannot fire the same daily workflow twice.
        """
        while True:
            try:
                for job in due_workflows():
                    if not self.session:
                        continue
                    device_id = job.get("device_id")
                    if device_id and self._dashboard:
                        # Route generated speech back to the companion on which
                        # this schedule was created, if that companion is online.
                        if device_id in self._dashboard._device_sockets:
                            self._dashboard._active_voice_device = device_id
                    instruction = (
                        "[SCHEDULED USER WORKFLOW] Execute this user-created recurring "
                        "instruction now. Use your normal tools as needed and obtain "
                        "time-sensitive information now, not from when it was scheduled. "
                        "Speak the result naturally to the user. Instruction: "
                        + str(job.get("command", ""))
                    )
                    await self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": instruction}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(
                        f"[Schedule] Ran {job.get('id')} — {job.get('command', '')[:80]}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"[Schedule] {e}")
            await asyncio.sleep(20)

    async def _on_attachment_result(self, source_device, destination_device, summary):
        """Resume the requested voice task only after its files are available."""
        if not self.session or not self._dashboard or source_device not in self._dashboard._device_sockets:
            return
        completed = int(summary.get("completed", 0))
        failed = int(summary.get("failed", 0))
        if destination_device == "server":
            names = [item.get("name") for item in summary.get("items", []) if item.get("ok")]
            instruction = (
                "[SERVER FILE STORAGE RESULT] This is the result of the user's prior voice request, "
                "not a new request. The following file names were permanently stored in the "
                f"Mark server object store: {json.dumps(names, ensure_ascii=False)}. "
                f"{failed} file(s) failed. Confirm the stored files to the user in their current "
                "language. Do not claim to have edited their contents or call transfer_file again."
            )
        else:
            target = self._dashboard._mesh.get(destination_device) or {}
            target_name = target.get("name") or "the destination companion"
            instruction = (
                "[ATTACHMENT TRANSFER RESULT] This is a system event for the user-requested "
                f"transfer, not a new request. {completed} file(s) were sent to the attachment "
                f"inbox of {target_name}; {failed} failed. Tell the user briefly in their "
                "current language. The recipient has not necessarily saved them. "
                "Do not call transfer_file again."
            )
        self._dashboard._active_voice_device = source_device
        await self.session.send_client_content(
            turns={"role":"user", "parts":[{"text":instruction}]}, turn_complete=True,
        )

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    # A remote command is deliberate control and the phone user
                    # has no desktop WAKE button — so it wakes JARVIS if asleep.
                    if self._wake_enabled and not self._awake:
                        self.wake(reason="remote command")
                    await self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._reconnect_event = asyncio.Event()

        # ── Wire the shared core services to the interface ───────────────────
        # The confirmation gate is useless without a way to ask, and a memory
        # trim is invisible without a way to say so. Both are bound once here
        # rather than passed down through every action signature.
        confirm_gate.bind(
            show = self.ui.show_confirm,
            hide = self.ui.hide_confirm,
            log  = self.ui.write_log,
        )
        set_trim_notifier(self.ui.write_log)

        # Server runtime is intentionally audio-device agnostic. Microphone capture
        # and speaker playback belong to companion clients, so a headless server
        # never enumerates or opens local audio hardware.

        # The HTTP API is a required server boundary: companions, pairing,
        # health checks, file transfer, and the public tunnel all depend on it.
        # Never leave a detached worker alive when this boundary cannot start.
        try:
            from dashboard.server import DashboardServer
            from core.network_config import DASHBOARD_PORT
            self._dashboard = DashboardServer()
            self._dashboard.set_interrupt_callback(self.interrupt)
            self._dashboard.set_attachment_result_callback(self._on_attachment_result)
            self._dashboard.assert_port_available()
            self._dashboard_task = asyncio.create_task(self._dashboard.serve())
            # Give the task a bounded startup window. If it returns/raises before
            # Uvicorn owns the port, propagate the actual exception to stderr.
            deadline = asyncio.get_running_loop().time() + 10.0
            api_ready = False
            while asyncio.get_running_loop().time() < deadline:
                if self._dashboard_task.done():
                    await self._dashboard_task
                    raise RuntimeError("Mark HTTP API stopped during startup")
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection("127.0.0.1", DASHBOARD_PORT), timeout=0.5
                    )
                    writer.close()
                    await writer.wait_closed()
                    api_ready = True
                    break
                except (OSError, asyncio.TimeoutError):
                    await asyncio.sleep(0.1)
            if not api_ready:
                raise RuntimeError(
                    f"Mark HTTP API did not bind to 127.0.0.1:{DASHBOARD_PORT} within 10 seconds"
                )
            # Runs for the whole lifetime, not just inside an active session.
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[ERROR] Mark HTTP API startup failed: {e}", file=sys.stderr)
            raise

        while True:
            live_model = _gemini.live_model()
            try:
                if self._dashboard:
                    self._dashboard.set_phone_audio_enabled(False)
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                _resumed_with = self._resume_handle is not None
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state
                # v1alpha carries proactive audio; if it gets rejected we fall
                # back to v1beta.
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1alpha" if self._enhanced_live else "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=live_model, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self._session_generation += 1
                    self._last_live_connected_at = time.monotonic()
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()
                    self._live_progress_seq = 0
                    self._voice_turn_seq = 0
                    self._pending_voice_turns = []
                    self._unanswered_voice_turns = 0
                    if self._dashboard:
                        self._dashboard.set_phone_audio_enabled(True)

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False
                    self._phone_activity_active = False
                    self._phone_last_voice     = 0.0

                    print("[JARVIS] Connected.")
                    _trace_event("live_connected", model=live_model, session=self._session_generation)
                    if self._recovery_context_pending:
                        self.ui.write_log("SYS: Reconnected — conversation context recovered locally.")
                        self._recovery_context_pending = False
                    if _resumed_with:
                        # Say it plainly: the difference between "it reconnected"
                        # and "it reconnected and still knows what we were doing"
                        # is the whole point, and it is invisible otherwise.
                        self.ui.write_log("SYS: Reconnected — conversation restored.")

                    _unfinished = task_state.active()
                    _last_task_action = (_unfinished.get("last_action") or {}) if _unfinished else {}
                    if (_unfinished and _unfinished.get("status") != "WAITING"
                            and _last_task_action.get("state") == "STARTED"):
                        task_state.resume()
                        async def _resume_unfinished_task():
                            await asyncio.sleep(0.35)
                            try:
                                await self.session.send_client_content(
                                    turns={"role": "user", "parts": [{"text": task_state.recovery_instruction()}]},
                                    turn_complete=True,
                                )
                            except Exception as _task_exc:
                                print(f"[TaskContinuity] Resume injection deferred: {_task_exc}")
                        asyncio.create_task(_resume_unfinished_task())

                    # Wake word: if enabled, come up ASLEEP (mic gated, silent)
                    # until the user says "Hey Jarvis" or taps wake in the UI.
                    if self._wake_enabled:
                        self._ensure_wake_detector()
                        self._awake = False
                        self.ui.set_state("SLEEPING")
                        self.ui.write_log("SYS: JARVIS online — sleeping. Say 'Hey Jarvis' to wake me.")
                    else:
                        self._awake = True
                        self.ui.set_state("LISTENING")
                        self.ui.write_log("SYS: JARVIS online.")

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    self._reconnect_event.clear()  # ignore requests from before this session
                    tg.create_task(self._watch_reconnect())
                    tg.create_task(self._watch_live_stall())
                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    # System monitoring remains available on demand; no unsolicited server alerts.
                    tg.create_task(self._run_background_monitor())
                    # Do not run unsolicited proactive check-ins. Mark stays idle
                    # unless the user speaks or a user-created scheduled workflow is due.
                    tg.create_task(self._run_scheduled_workflows())
                    tg.create_task(self._run_sleep_watch())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())


            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                # Voluntary reconnect (voice change) — not an error. Rebuild the
                # session immediately with no backoff and no scary logs.
                if _is_reconnect_signal(e):
                    print("[JARVIS] Voluntary reconnect requested.")
                    if not _keep_context_of(e):
                        # A deliberate clean slate (voice change) — drop the
                        # handle so the next connect really does start empty.
                        self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                # A resumption handle the server will not accept — expired, or
                # belonging to a session it has since dropped. Without this, the
                # same dead handle would be replayed on every retry and the
                # assistant would never come back at all: the feature meant to
                # survive a reconnect would be the thing preventing one. Drop it
                # once and let the next attempt start clean.
                _flat_err = _exception_text(e)
                _flat_lower = _flat_err.lower()
                _error_detail = _bounded_exception_text(e)
                if not _error_detail:
                    _error_detail = type(e).__name__
                if _resumed_with and not _is_transient_transport_error(e) and (
                    "resumption handle" in _flat_lower
                    or "session resumption" in _flat_lower
                    or "invalid handle" in _flat_lower
                    or ("invalid_argument" in _flat_lower and "resum" in _flat_lower)
                    or ("not_found" in _flat_lower and "resum" in _flat_lower)
                ):
                    print("[JARVIS] 🔗 Resumption handle rejected — starting a fresh session")
                    self.ui.write_log("SYS: Session handle expired — recovering conversation context locally.")
                    self._recovery_context_pending = bool(self._session_log)
                    self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                err_str = _flat_err
                _err_lower = _flat_lower
                decision = classify_error(Boundary.LIVE_SESSION, e)
                _trace_event(
                    "runtime_error",
                    boundary=decision.boundary.value,
                    category=decision.category,
                    action=decision.action.value,
                    retryable=decision.retryable,
                    error_type=type(e).__name__,
                    error=_error_detail,
                )

                # A provider/model failure should select the next compatible
                # Live rung; transport failures must keep the current model and
                # use normal reconnect backoff instead.
                if (decision.action is ErrorAction.MODEL_FAILOVER
                        and _gemini.note_live_failure(live_model, err_str)):
                    next_live_model = _gemini.live_model()
                    if next_live_model != live_model:
                        self.ui.write_log(
                            f"SYS: Live model unavailable — switching to {next_live_model}."
                        )
                        self._conn_backoff = 0
                        continue

                # Transport/session rollover errors need the dedicated handler
                # below. In particular, a keepalive ping timeout is a transport
                # break, not evidence that the latest resumption handle is bad.
                # Previously BOUNDED_FAILURE consumed it here first, discarded
                # the handle, and made an ordinary reconnect look like a new
                # conversation.
                _is_rollover_transport = (
                    "goaway" in _err_lower
                    or "session durat" in _err_lower
                    or "session expired" in _err_lower
                    or ("1008" in _err_lower and (
                        "failed to close" in _err_lower
                        or "operation was aborted" in _err_lower
                    ))
                    or "keepalive ping timeout" in _err_lower
                    or "timed out while closing connection" in _err_lower
                )

                # Unknown Live-session failures must start a clean provider
                # session. Reusing a possibly-invalid handle can leave the
                # Companion connected but permanently silent after recovery.
                if decision.action is ErrorAction.BOUNDED_FAILURE and not _is_rollover_transport:
                    self._recovery_context_pending = bool(self._session_log)
                    self._resume_handle = None
                    self._conn_backoff = min(max(getattr(self, "_conn_backoff", 1) * 2, 2), 30)
                    self.ui.write_log(
                        "SYS: Live session failed — reconnecting with a clean session."
                    )
                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "reconnecting"})
                    await asyncio.sleep(self._conn_backoff)
                    continue

                # Gemini Live sends GoAway when a finite live session reaches its
                # duration limit. Treat that as a normal rollover and reconnect
                # with the latest session-resumption handle instead of dumping a
                # TaskGroup/1008 traceback.
                if _is_rollover_transport:
                    # Gemini may surface normal Live-session rollover either as a
                    # GoAway, a provider session-expired policy close, or a
                    # WebSocket 1008. Expired sessions cannot be resumed with the
                    # old handle; clear it and reconnect cleanly.
                    expired = "session expired" in _err_lower
                    print("[JARVIS] Live session rollover — reconnecting.")
                    self._recovery_context_pending = bool(self._session_log)
                    if expired:
                        self._resume_handle = None
                    dropped = self._dashboard.set_phone_audio_enabled(False) if self._dashboard else 0
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=200)
                    self._phone_activity_active = False
                    _trace_event("live_reconnect", reason="session_expired", dropped_phone_frames=dropped)
                    connected_for = time.monotonic() - getattr(self, "_last_live_connected_at", time.monotonic())
                    if connected_for >= 60:
                        self._conn_backoff = 1
                    else:
                        self._conn_backoff = min(max(getattr(self, "_conn_backoff", 1) * 2, 2), 30)
                    # Do not spin a reconnect storm when Gemini closes a session
                    # immediately. The paired device remains connected; only the
                    # provider session is delayed and rebuilt.
                    await asyncio.sleep(self._conn_backoff)
                    continue
                # Transient network loss is an availability state, not a code
                # failure.  Keep retry/backoff active without flooding error.log
                # with a full traceback on every reconnect attempt.
                _is_transient_network = _is_transient_transport_error(e)
                if not _is_transient_network:
                    print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                    traceback.print_exc()

                # Turn-taking / media / thinking knobs rejected by the server
                # (preview API drift) — drop them first, because they are the
                # newest fields and the cheapest to lose. Proactive audio is
                # tried again on the next pass if the error persists.
                if self._tuned_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                    or "realtime_input" in err_str.lower()
                    or "media_resolution" in err_str.lower()
                    or "thinking" in err_str.lower()
                ):
                    self._tuned_live = False
                    print("[JARVIS] Live tuning rejected — reconnecting without it.")
                    continue

                # Proactive audio rejected by the server (preview API drift) —
                # drop it and reconnect with the plain config.
                if self._enhanced_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "proactiv" in err_str.lower()
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                ):
                    self._enhanced_live = False
                    self.ui.write_log(
                        "SYS: Proactive audio unavailable — reconnecting without it."
                    )
                    continue

                # Invalid API key — stop hammering the API, prompt re-configuration
                if any(marker in err_str.lower() for marker in (
                    "api key not valid", "api_key_invalid", "invalid api key",
                    "api key expired", "permission_denied: api key"
                )):
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    # Desktop UI can collect a replacement key in-place. CLI/background
                    # deliberately never reach into Qt internals: CLI may run the shared
                    # terminal setup, while background fails closed and must be restarted.
                    if getattr(self.ui, "cli", False):
                        from core.setup_config import interactive_setup
                        if not await asyncio.to_thread(interactive_setup, True):
                            raise RuntimeError("API key reconfiguration cancelled")
                    elif self.ui.__class__.__name__ == "HeadlessInterface":
                        raise RuntimeError("API key invalid. Run: python main.py --setup")
                    else:
                        while not self.ui._win._ready:
                            await asyncio.sleep(1)
                    print("[JARVIS] New API key saved — reconnecting...")
                    _conn_backoff = 3
                    continue

                # Network / timeout errors — log clearly and back off
                is_net_err = _is_transient_network
                if is_net_err:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Connection failed — retrying in {_conn_backoff}s. "
                        "(a VPN may be required)"
                    )
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None
                if self._dashboard:
                    self._dashboard.set_phone_audio_enabled(False)
                # A transport/session rollover is not the end of the user's
                # conversation. Keep the transcript in RAM so an expired provider
                # resumption handle can be recovered locally on the next connect.

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

from core.server_lifecycle import (
    _runtime_paths, _runtime_mode, _spawn_server, _stop_server,
    _autostart_enable, _autostart_disable, _pair_device,
)

def main(argv=None):
    mode=_runtime_mode(argv)
    if mode=="start": _spawn_server(); return
    if mode=="stop": _stop_server(); return
    if mode=="enable": _autostart_enable(); return
    if mode=="disable": _autostart_disable(); return
    if mode.startswith("pair:"): _pair_device(mode.split(":", 1)[1] or None); return
    from core.runtime_log import configure_runtime_log
    _, logfile = _runtime_paths()
    configure_runtime_log(logfile)
    from core.interfaces import ServerInterface
    interface=ServerInterface(); interface.wait_for_api_key(); jarvis=JarvisLive(interface)
    # Wake-word capture is a client concern in server-only mode; never open a server microphone.
    jarvis._wake_enabled = False
    jarvis._awake = True
    pidfile,_=_runtime_paths(); pidfile.write_text(str(os.getpid()),encoding="utf-8")
    try: asyncio.run(jarvis.run())
    finally:
        try:
            if pidfile.exists() and pidfile.read_text().strip()==str(os.getpid()): pidfile.unlink()
        except Exception: pass

if __name__ == "__main__": main()
