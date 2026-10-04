"""Product-neutral runtime error classification across service boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Boundary(str, Enum):
    LIVE_SESSION = "live_session"
    COMPANION_SOCKET = "companion_socket"
    FILE_TRANSFER = "file_transfer"
    TUNNEL = "tunnel"
    TASK = "task"


class ErrorAction(str, Enum):
    SESSION_ROLLOVER = "session_rollover"
    MODEL_FAILOVER = "model_failover"
    TRANSPORT_RECONNECT = "transport_reconnect"
    COMPANION_RECONNECT = "companion_reconnect"
    BOUNDED_FAILURE = "bounded_failure"


@dataclass(frozen=True)
class ErrorDecision:
    boundary: Boundary
    category: str
    action: ErrorAction
    retryable: bool
    traceback: bool


def _text(error: object) -> str:
    return str(error).casefold()


def _is_transport(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "connecttimeout",
            "connection reset",
            "connection refused",
            "connection closed",
            "connection error",
            "no close frame",
            "timed out",
            "timeout",
            "keepalive ping timeout",
            "origin eof",
            "eof",
            "network is unreachable",
            "temporary failure in name resolution",
        )
    )


def _is_model_failure(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "429",
            "resource_exhausted",
            "503",
            "504",
            "unavailable",
            "404",
            "not found",
            "403",
            "permission_denied",
            "permission denied",
            "is not supported",
        )
    )


def classify_error(boundary: Boundary, error: object) -> ErrorDecision:
    """Map an error to a bounded action without deciding policy at call sites."""
    boundary = Boundary(boundary)
    text = _text(error)

    if boundary is Boundary.LIVE_SESSION:
        if any(marker in text for marker in ("goaway", "session duration", "session expired")):
            return ErrorDecision(boundary, "live_rollover", ErrorAction.SESSION_ROLLOVER, True, False)
        if _is_model_failure(text) and not _is_transport(text):
            return ErrorDecision(boundary, "model_failure", ErrorAction.MODEL_FAILOVER, True, False)
        if _is_transport(text):
            return ErrorDecision(boundary, "live_transport", ErrorAction.TRANSPORT_RECONNECT, True, False)

    if boundary is Boundary.COMPANION_SOCKET and _is_transport(text):
        return ErrorDecision(boundary, "companion_transport", ErrorAction.COMPANION_RECONNECT, True, False)

    if boundary is Boundary.TUNNEL and _is_transport(text):
        return ErrorDecision(boundary, "tunnel_transport", ErrorAction.TRANSPORT_RECONNECT, True, False)

    if boundary is Boundary.FILE_TRANSFER:
        return ErrorDecision(boundary, "file_transfer", ErrorAction.BOUNDED_FAILURE, False, False)

    return ErrorDecision(boundary, "isolated_failure", ErrorAction.BOUNDED_FAILURE, False, True)
