"""Per-request tokens must prevent a stale approval for a repeated action key."""
from core import confirm
from types import SimpleNamespace


def test_request_id_is_unique_and_stale_response_cannot_authorize(monkeypatch):
    events = []
    monkeypatch.setattr(confirm, "_pending", None)
    confirm.bind(lambda title, detail: None, lambda: None)
    monkeypatch.setattr(confirm.threading, "Timer", lambda *args, **kwargs: SimpleNamespace(start=lambda: None, cancel=lambda: None))
    monkeypatch.setattr(confirm.threading, "Thread", lambda *args, **kwargs: events.append("executed"))
    assert "CONFIRMATION_PENDING" in confirm.request("shutdown", "Shutdown", "Now", lambda: "done")
    first = confirm.pending_request()
    assert first and first["request_id"]
    confirm.resolve(False, expected_request_id=first["request_id"])
    assert "CONFIRMATION_PENDING" in confirm.request("shutdown", "Shutdown", "Again", lambda: "done")
    second = confirm.pending_request()
    assert second["request_id"] != first["request_id"]
    confirm.resolve(True, expected_request_id=first["request_id"])
    assert confirm.pending_request()["request_id"] == second["request_id"]
    assert events == []
    confirm.resolve(False, expected_request_id=second["request_id"])
    monkeypatch.setattr(confirm, "_pending", None)
