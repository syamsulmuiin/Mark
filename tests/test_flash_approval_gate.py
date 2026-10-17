"""Fail-closed approval gate regression tests."""
import importlib
import core.confirm as confirm


def setup_function():
    importlib.reload(confirm)


def test_timeout_defaults_to_fifteen_seconds():
    assert confirm.TIMEOUT_SECONDS == 15.0


def test_no_ui_refuses_execution():
    ran = []
    result = confirm.request("delete", "Delete", "file", lambda: ran.append(True))
    assert "cannot confirm" in result
    assert not ran


def test_pending_cannot_be_replaced_and_stale_reply_is_ignored():
    shown = []
    confirm.bind(lambda title, detail: shown.append(title), lambda: None)
    confirm.request("first", "First", "details", lambda: "first")
    msg = confirm.request("second", "Second", "details", lambda: "second")
    assert "still pending" in msg
    assert shown == ["First"]
    confirm.resolve(False, expected_key="second")
    assert confirm.pending_title() == "First"
    confirm.resolve(False, expected_key="first")
    assert confirm.pending_title() == ""


def test_expired_confirmation_never_executes(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(confirm.time, "monotonic", lambda: clock[0])
    ran = []
    confirm.bind(lambda *_: None, lambda: None)
    confirm.request("first", "First", "details", lambda: ran.append(True))
    clock[0] += 16
    confirm.resolve(True, expected_key="first")
    assert not ran
