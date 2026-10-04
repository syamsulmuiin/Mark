import pytest

from core.runtime_errors import (
    Boundary,
    ErrorAction,
    classify_error,
)


@pytest.mark.parametrize(
    ("boundary", "message", "action"),
    [
        (Boundary.LIVE_SESSION, "GoAway: session duration limit", ErrorAction.SESSION_ROLLOVER),
        (Boundary.LIVE_SESSION, "503 UNAVAILABLE", ErrorAction.MODEL_FAILOVER),
        (Boundary.LIVE_SESSION, "connection reset by peer", ErrorAction.TRANSPORT_RECONNECT),
        (Boundary.COMPANION_SOCKET, "no close frame received", ErrorAction.COMPANION_RECONNECT),
        (Boundary.FILE_TRANSFER, "ETIMEDOUT while downloading", ErrorAction.BOUNDED_FAILURE),
        (Boundary.TUNNEL, "origin EOF", ErrorAction.TRANSPORT_RECONNECT),
    ],
)
def test_classifies_failures_by_boundary(boundary, message, action):
    decision = classify_error(boundary, message)
    assert decision.action == action
    assert decision.boundary == boundary
    assert decision.category


def test_unknown_error_stays_isolated():
    decision = classify_error(Boundary.TASK, RuntimeError("unexpected failure"))
    assert decision.action == ErrorAction.BOUNDED_FAILURE
    assert decision.retryable is False
    assert decision.traceback is True


def test_network_failure_does_not_trigger_model_failover():
    decision = classify_error(Boundary.LIVE_SESSION, "ConnectTimeout: all attempts failed")
    assert decision.action == ErrorAction.TRANSPORT_RECONNECT
    assert decision.action != ErrorAction.MODEL_FAILOVER
    assert decision.retryable is True
