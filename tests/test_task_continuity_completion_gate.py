import json
from pathlib import Path

from core import task_continuity as tc


def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(tc, "STATE_DIR", tmp_path)
    monkeypatch.setattr(tc, "STATE_FILE", tmp_path / "active_task.json")
    tc.begin("Create an artifact and deliver it", completion_criteria="Artifact and delivery verified")


def test_empty_or_unanchored_completion_is_rejected(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    assert not tc.complete("")
    assert not tc.complete("model says it is done")
    assert tc.active()["status"] == "IN_PROGRESS"


def test_checkpoint_requires_finished_real_action_and_evidence(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    assert not tc.checkpoint("claimed milestone", "claim only")
    tc.action_started("send_server_file", {"source": "/tmp/report.pdf"})
    assert not tc.checkpoint("sent", "notified")
    tc.action_finished("send_server_file", json.dumps({"status": "notified", "attachment_id": "a1"}))
    assert not tc.checkpoint("sent", "")
    assert tc.checkpoint("sent", "attachment a1 notified")


def test_task_continuity_bookkeeping_does_not_replace_real_action(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    tc.action_started("send_server_file", {})
    tc.action_finished("send_server_file", '{"status":"notified"}')
    before = tc.active()["last_action"]
    tc.action_started("task_continuity", {"action": "checkpoint"})
    tc.action_finished("task_continuity", "Checkpoint saved.")
    assert tc.active()["last_action"] == before


def test_completion_requires_checkpoint_for_latest_action(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    tc.action_started("create_document", {})
    tc.action_finished("create_document", "created report.pdf")
    assert tc.checkpoint("document created", "report.pdf exists")
    tc.action_started("send_server_file", {})
    tc.action_finished("send_server_file", '{"status":"notified","attachment_id":"a1"}')
    assert not tc.complete("all requested work completed")
    assert tc.checkpoint("delivery verified", "attachment a1 notified")
    assert tc.complete("artifact creation and inbox delivery verified")
    data = json.loads((tmp_path / "active_task.json").read_text())
    assert data["status"] == "COMPLETED"
    assert data["completion_evidence"]
