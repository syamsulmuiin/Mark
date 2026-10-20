"""New user turns may request a fresh gate; provider replay cannot."""
import threading
import pytest
from core import confirm


@pytest.fixture(autouse=True)
def gate(monkeypatch):
    monkeypatch.setattr(confirm, "_pending", None)
    monkeypatch.setattr(confirm, "_recent_proposals", {})
    monkeypatch.setattr(confirm, "_recent_proposal_scopes", {})
    confirm.bind(lambda *_: None, lambda: None)
    yield
    pending = confirm.pending_request()
    if pending:
        confirm.resolve(False, expected_request_id=pending["request_id"])
    confirm.bind(None, None)


@pytest.mark.parametrize("expired", [False, True])
def test_new_turn_after_rejection_or_expiry_gets_a_fresh_gate(monkeypatch, expired):
    calls = []
    def request(scope):
        return confirm.request("text_proposal:restart", "Restart", "Server",
                               lambda: calls.append(True), scope=scope)
    assert request("1:1").startswith("[CONFIRMATION_PENDING]")
    old = confirm.pending_request()["request_id"]
    if expired:
        confirm._pending.at -= confirm.TIMEOUT_SECONDS + 1
    confirm.resolve(False, expected_request_id=old)
    assert request("1:1").startswith("[CONFIRMATION_COMPLETED]")
    assert request("1:2").startswith("[CONFIRMATION_PENDING]")
    fresh = confirm.pending_request()["request_id"]
    assert fresh != old
    confirm.resolve(True, expected_request_id=old)
    assert confirm.pending_request()["request_id"] == fresh
    assert calls == []


def test_running_action_stays_blocked_across_turns():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def run():
        started.set()
        release.wait(2)
        return "done"
    confirm.bind(lambda *_: None, lambda: None, on_result=lambda *_: finished.set())
    confirm.request("text_proposal:restart", "Restart", "Server", run, scope="1:1")
    confirm.resolve(True, expected_request_id=confirm.pending_request()["request_id"])
    assert started.wait(1)
    try:
        result = confirm.request("text_proposal:restart", "Restart", "Server", run, scope="1:2")
        assert result.startswith("[CONFIRMATION_COMPLETED]")
        assert confirm.pending_request() is None
    finally:
        release.set()
        assert finished.wait(2)
