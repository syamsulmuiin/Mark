"""
core/confirm.py — a confirmation the model cannot forge.

THE PROBLEM WITH THE OLD GATE
    computer_settings guarded shutdown and restart like this:

        confirmed = str(params.get("confirmed", "")).lower()
        if confirmed not in ("yes", "true", "1", "confirm"):
            return "Please confirm by calling again with confirmed=yes."

    `confirmed` is a tool parameter, which means the *model* writes it. Nothing
    stops it from sending confirmed=yes on the first call, and nothing checks
    that a human was ever involved. It is a convention, not a gate — and its
    coverage was two actions, so deleting files and switching off the WiFi the
    assistant is talking over went through with no gate at all.

THE DESIGN HERE
    The confirmation token is issued by the *interface*, never by the model:

      1. An action calls `request(...)` with a callable that does the real work.
      2. This module hands the UI a banner with CONFIRM / CANCEL and returns
         IMMEDIATELY with a sentence for the model to say out loud.
      3. If — and only if — the user presses CONFIRM, the UI calls `resolve()`,
         which runs the stored callable off the Qt thread.

    Nothing blocks. The model keeps talking while the banner is up, so this
    costs no latency at all; in fact it is cheaper than the old gate, which
    burned two tool round trips (reject, then re-call) on every shutdown.

WHAT BELONGS HERE AND WHAT DOES NOT
    Only genuinely irreversible things. Anything that can be reversed should be
    done at once and pushed onto core/undo.py instead — undo is faster than a
    question, and an assistant that asks before every action is one nobody uses.
"""

from __future__ import annotations

import threading
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Optional

# A pending confirmation is abandoned after this long. Chosen to outlast a
# normal "hang on, let me look at the screen" pause without leaving a live
# shutdown button sitting on the HUD for the rest of the day.
TIMEOUT_SECONDS = 15.0


@dataclass
class _Pending:
    key:     str
    request_id: str
    title:   str
    detail:  str
    run:     Callable[[], str]
    at:      float
    scope: str = ""
    timer:   Optional[threading.Timer] = None


_pending: Optional[_Pending] = None
_lock = threading.Lock()
_recent_proposals: dict[str, tuple[float, str]] = {}
_recent_proposal_scopes: dict[str, str] = {}
PROPOSAL_REPLAY_SECONDS = 60.0

# Set once at startup by main.py. Signature: (title, detail) -> None for show,
# and () -> None for hide. Both are marshalled onto the Qt thread by the UI.
_show_cb: Optional[Callable[[str, str], None]] = None
_hide_cb: Optional[Callable[[], None]] = None
_log_cb:  Optional[Callable[[str], None]] = None
_result_cb: Optional[Callable[[str, str, str, bool, str], None]] = None
_decision_cb = None


def bind(show, hide, log=None, on_result=None, on_decision=None) -> None:
    """Wire this module to the HUD. Called once from main.py at startup."""
    global _show_cb, _hide_cb, _log_cb, _result_cb, _decision_cb
    _show_cb, _hide_cb, _log_cb, _result_cb = show, hide, log, on_result
    _decision_cb = on_decision


def _log(msg: str) -> None:
    if _log_cb:
        try:
            _log_cb(msg)
        except Exception:
            pass


def request(key: str, title: str, detail: str, run: Callable[[], str], *, scope: str = "") -> str:
    """Park an irreversible action behind the on-screen gate.

    Returns the sentence the tool should hand back to the model — phrased as an
    instruction so the assistant asks the user out loud in their own language,
    rather than reading an English string verbatim."""
    global _pending

    if _show_cb is None:
        # No interface bound (headless, or a very early call). Refuse rather
        # than silently performing something irreversible.
        return (f"I cannot confirm '{title}' right now because the interface is "
                f"not available, so I have not done it.")

    # If a busy scheduler delayed the timer, expire the old request before
    # allowing a replacement; its outcome must still be reported exactly once.
    with _lock:
        expired = _pending if _pending is not None and time.monotonic() - _pending.at >= TIMEOUT_SECONDS else None
    if expired is not None:
        resolve(False, expected_request_id=expired.request_id)

    with _lock:
        now = time.monotonic()
        for old_key, (at, state) in list(_recent_proposals.items()):
            if state != "running" and now - at > PROPOSAL_REPLAY_SECONDS:
                _recent_proposals.pop(old_key, None)
                _recent_proposal_scopes.pop(old_key, None)
        if key.startswith("text_proposal:") and key in _recent_proposals:
            state = _recent_proposals[key][1]
            if state == "running" or _recent_proposal_scopes.get(key, "") == scope:
                return (f"[CONFIRMATION_COMPLETED] This exact action was already handled ({state}). "
                        "Do not request approval or execute it again in this user turn.")
        # A new request must never silently replace an unanswered approval.
        # An expired request is discarded; the old callback can no longer run.
        if _pending is not None and time.monotonic() - _pending.at <= TIMEOUT_SECONDS:
            return ("Another confirmation is still pending. "
                    "Wait for the user to approve, reject, or let it expire.")
        _pending = _Pending(key=key, request_id=secrets.token_urlsafe(24), title=title, detail=detail,
                            run=run, at=time.monotonic(), scope=scope)
        p = _pending

    try:
        _show_cb(title, detail)
    except Exception as e:
        with _lock:
            if _pending is p:
                _pending = None
        return f"Could not ask for confirmation: {e}. Nothing was done."

    with _lock:
        if _pending is p:
            p.timer = threading.Timer(max(0.0, TIMEOUT_SECONDS - (time.monotonic() - p.at)),
                lambda: resolve(False, expected_request_id=p.request_id))
            p.timer.daemon = True
            p.timer.start()
    _log(f"SYS: Awaiting confirmation — {title}")
    return (
        f"[CONFIRMATION_PENDING] I have put a confirmation on screen for: {title}. "
        f"Say ONE short sentence in the user's own language telling them you need "
        f"them to confirm it on the HUD before you do it. Do not claim it is done."
    )


def _notify_result(p: _Pending, success: bool, result: str) -> None:
    """Optional completion signal; never let notification errors affect the gate."""
    if p.key.startswith("text_proposal:"):
        with _lock:
            _recent_proposals[p.key] = (time.monotonic(), "succeeded" if success else "not_executed_or_failed")
    if _result_cb:
        try:
            _result_cb(p.request_id, p.key, p.title, success, result)
        except Exception:
            pass


def _notify_decision(p: _Pending, outcome: str) -> None:
    if _decision_cb:
        try:
            _decision_cb(p.request_id, outcome)
        except Exception:
            pass


def resolve(accepted: bool, *, expected_key: Optional[str] = None,
            expected_request_id: Optional[str] = None) -> None:
    """Called by the UI when the user presses CONFIRM or CANCEL.

    Runs the stored callable on a worker thread — this is invoked from the Qt
    thread, and shutting the machine down from inside a button handler would
    freeze the interface on its way out."""
    global _pending

    with _lock:
        # Remote companion responses must identify the exact pending request.
        # Reject stale or mismatched responses without consuming the new one.
        if expected_key is not None and (_pending is None or _pending.key != expected_key):
            return
        if expected_request_id is not None and (_pending is None or _pending.request_id != expected_request_id):
            return
        p, _pending = _pending, None
        if p is not None and p.key.startswith("text_proposal:"):
            _recent_proposals[p.key] = (time.monotonic(), "running" if accepted else "rejected")
            _recent_proposal_scopes[p.key] = p.scope

    if p is not None and p.timer is not None:
        p.timer.cancel()

    if _hide_cb:
        try:
            _hide_cb()
        except Exception:
            pass

    if p is None:
        return

    if time.monotonic() - p.at >= TIMEOUT_SECONDS:
        _notify_decision(p, "expired")
        _log(f"SYS: Confirmation expired — {p.title}")
        _notify_result(p, False, "expired")
        return

    if not accepted:
        _notify_decision(p, "rejected")
        _log(f"SYS: Cancelled — {p.title}")
        _notify_result(p, False, "rejected")
        return

    _notify_decision(p, "accepted")

    def _worker():
        try:
            from core.action_outcomes import assess
            result = p.run()
            if isinstance(result, dict):
                import json
                result = json.dumps(result, ensure_ascii=False)
            outcome = assess(result)
            _log(f"SYS: Confirmed — {p.title}. {result}")
            nested = str(result).startswith("[CONFIRMATION_PENDING]")
            _notify_result(p, outcome == "VERIFIED" and not nested,
                "nested_confirmation_pending" if nested else
                "unverified" if outcome == "UNVERIFIED" else
                "waiting" if outcome == "WAITING" else result)
        except Exception as e:
            _log(f"ERR: {p.title} failed — {e}")
            _notify_result(p, False, "failed")

    threading.Thread(target=_worker, daemon=True,
                     name=f"confirm-{p.key}").start()


def pending_title() -> str:
    """'' when nothing is waiting. Lets an action avoid stacking two banners."""
    with _lock:
        if _pending is None:
            return ""
        if time.monotonic() - _pending.at > TIMEOUT_SECONDS:
            return ""
        return _pending.title


def pending_request() -> Optional[dict]:
    """Return a safe, immutable snapshot for delivery to a companion."""
    with _lock:
        p = _pending
        if p is None or time.monotonic() - p.at > TIMEOUT_SECONDS:
            return None
        return {"request_id": p.request_id, "title": p.title,
                "detail": p.detail, "timeout_seconds": TIMEOUT_SECONDS}


def response_metadata(result: str) -> dict:
    """A spoken confirmation request must correspond to a live displayed gate."""
    displayed = str(result).startswith("[CONFIRMATION_PENDING]") and pending_request() is not None
    return {"approval_required": displayed, "approval_sent": displayed}
