"""Completion callbacks must reflect actual action execution, not just approval."""
import threading
from core import confirm


def test_completion_fires_after_approved_action(monkeypatch):
    monkeypatch.setattr(confirm, "_pending", None)
    completed = threading.Event()
    events = []
    confirm.bind(lambda *_: None, lambda: None,
                 on_result=lambda request_id, key, title, ok, result: (events.append((key, ok, result)), completed.set()))
    confirm.request("flash_approval_smoke_test", "Test", "Safe", lambda: "done")
    pending = confirm.pending_request()
    assert pending
    confirm.resolve(True, expected_request_id=pending["request_id"])
    assert completed.wait(2)
    assert events == [("flash_approval_smoke_test", True, "done")]
    confirm.bind(lambda *_: None, lambda: None)


def test_rejected_action_reports_without_execution(monkeypatch):
    monkeypatch.setattr(confirm, "_pending", None)
    events = []
    confirm.bind(lambda *_: None, lambda: None,
                 on_result=lambda request_id, key, title, ok, result: events.append((ok, result)))
    confirm.request("flash_approval_smoke_test", "Test", "Safe",
                    lambda: (_ for _ in ()).throw(AssertionError("must not execute")))
    pending = confirm.pending_request()
    assert pending
    confirm.resolve(False, expected_request_id=pending["request_id"])
    assert events == [(False, "rejected")]
    confirm.bind(lambda *_: None, lambda: None)
