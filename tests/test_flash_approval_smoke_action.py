"""Smoke test tool must only create a confirmation, never execute side effects."""
from actions.test_flash_approval import test_flash_approval
from core import confirm


def test_smoke_action_creates_pending_confirmation(monkeypatch):
    monkeypatch.setattr(confirm, "_pending", None)
    shown = []
    confirm.bind(lambda title, detail: shown.append((title, detail)), lambda: None)
    result = test_flash_approval({})
    assert "[CONFIRMATION_PENDING]" in result
    assert shown and shown[0][0] == "Tes Flash Approval"
    assert confirm.pending_request() is not None
    confirm.resolve(False, expected_request_id=confirm.pending_request()["request_id"])
    monkeypatch.setattr(confirm, "_pending", None)
