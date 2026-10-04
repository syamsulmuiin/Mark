from pathlib import Path
import json
import pytest

from core import repair_engine as r


def _sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "BASE_DIR", tmp_path)
    monkeypatch.setattr(r, "STATE_DIR", tmp_path / "storage/self_repair")
    monkeypatch.setattr(r, "TX_DIR", tmp_path / "storage/self_repair/transactions")
    monkeypatch.setattr(r, "KNOWLEDGE_DIR", tmp_path / "storage/self_repair/knowledge")
    monkeypatch.setattr(r, "AUDIT_FILE", tmp_path / "storage/self_repair/audit.jsonl")


def test_path_traversal_and_protected_files_rejected():
    with pytest.raises(r.RepairPolicyError): r.normalize_rel("../outside.py")
    with pytest.raises(r.RepairPolicyError): r.enforce_policy(["core/repair_engine.py"], 1, "low", False)


def test_high_risk_requires_separate_approval():
    with pytest.raises(r.RepairPolicyError): r.enforce_policy(["main.py"], 10, "high", False)
    assert r.enforce_policy(["main.py"], 10, "high", True).risk == "high"


def test_snapshot_and_full_rollback(monkeypatch, tmp_path):
    _sandbox(monkeypatch, tmp_path)
    (tmp_path / "a.py").write_text("A", encoding="utf-8")
    (tmp_path / "b.py").write_text("B", encoding="utf-8")
    tx = r.begin_transaction("repair", "medium", {"a.py":"A", "b.py":"B"}, ["test"])
    r.write_candidate("a.py", "AA"); r.write_candidate("b.py", "BB")
    restored = r.rollback(tx)
    assert set(restored) == {"a.py", "b.py"}
    assert (tmp_path / "a.py").read_text() == "A"
    assert (tmp_path / "b.py").read_text() == "B"
    assert json.loads((r.TX_DIR / tx / "manifest.json").read_text())["status"] == "ROLLED_BACK"


def test_audit_redacts_secrets(monkeypatch, tmp_path):
    _sandbox(monkeypatch, tmp_path)
    r.audit("test", message="api_key=supersecret password=hunter2")
    text = r.AUDIT_FILE.read_text()
    assert "supersecret" not in text and "hunter2" not in text
    assert "<redacted>" in text


def test_knowledge_promotion_and_search(monkeypatch, tmp_path):
    _sandbox(monkeypatch, tmp_path)
    r.record_knowledge("fixes", {"problem":"websocket reconnect race", "confidence":"CONFIRMED", "validation_status":"verified"})
    found = r.search_knowledge("reconnect websocket")
    assert found and found[0]["confidence"] == "CONFIRMED"


def test_change_budget_and_duplicate_rejected():
    with pytest.raises(r.RepairPolicyError): r.enforce_policy(["main.py", "main.py"], 2, "low", False)
    with pytest.raises(r.RepairPolicyError): r.enforce_policy(["main.py"], r.MAX_DIFF_CHARS + 1, "low", False)


def test_validation_timeout_is_failure(monkeypatch, tmp_path):
    _sandbox(monkeypatch, tmp_path)
    class TimeoutRun:
        def __call__(self, *a, **kw):
            import subprocess
            raise subprocess.TimeoutExpired(cmd=a[0], timeout=kw.get("timeout", 1))
    monkeypatch.setattr(r.subprocess, "run", TimeoutRun())
    ok, results = r.validate_repository(["main.py"], timeout=1)
    assert not ok and results[0]["output"] == "validation timeout"


def test_invalid_knowledge_category_rejected(monkeypatch, tmp_path):
    _sandbox(monkeypatch, tmp_path)
    with pytest.raises(r.RepairPolicyError): r.record_knowledge("trusted", {"x": 1})


def test_interrupted_candidate_is_recovered(monkeypatch, tmp_path):
    _sandbox(monkeypatch, tmp_path)
    (tmp_path / "a.py").write_text("stable", encoding="utf-8")
    tx = r.begin_transaction("repair", "low", {"a.py":"stable"}, ["test"])
    r.write_candidate("a.py", "candidate")
    r.set_status(tx, "CANDIDATE_WRITTEN")
    assert (tmp_path / "a.py").read_text() == "candidate"
    assert r.recover_incomplete_transactions() == [tx]
    assert (tmp_path / "a.py").read_text() == "stable"


def test_human_approval_language_gate():
    from core.language_compat import has_explicit_repair_apply_intent, has_explicit_high_risk_approval
    assert has_explicit_repair_apply_intent("lakukan perbaikan itu")
    assert has_explicit_repair_apply_intent("apply the repair")
    assert not has_explicit_high_risk_approval("lakukan perbaikan itu")
    assert has_explicit_high_risk_approval("saya setujui risiko tinggi ini")
    assert has_explicit_high_risk_approval("approve this high-risk repair")


def _apply_params(old="x = 1", new="x = 2"):
    return {"apply": True, "authorization": "APPLY_DIAGNOSTIC_REPAIR", "confidence": "high", "risk": "low", "problem": "change test value", "attempt": 1, "operations": [{"file":"main.py", "old":old, "new":new}]}


def test_apply_success_transaction(monkeypatch, tmp_path):
    import actions.self_repair_apply as a
    _sandbox(monkeypatch, tmp_path); monkeypatch.setattr(a, "BASE_DIR", tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(a, "recover_incomplete_transactions", lambda: [])
    monkeypatch.setattr(a, "validate_sandbox", lambda candidates: (True, [{"returncode":0}]))
    monkeypatch.setattr(a, "validate_repository", lambda files: (True, [{"returncode":0}]))
    result = a.self_repair_apply(_apply_params())
    assert "accepted" in result.lower()
    assert (tmp_path / "main.py").read_text() == "x = 2\n"


def test_post_write_failure_rolls_back_all(monkeypatch, tmp_path):
    import actions.self_repair_apply as a
    _sandbox(monkeypatch, tmp_path); monkeypatch.setattr(a, "BASE_DIR", tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(a, "recover_incomplete_transactions", lambda: [])
    monkeypatch.setattr(a, "validate_sandbox", lambda candidates: (True, [{"returncode":0}]))
    monkeypatch.setattr(a, "validate_repository", lambda files: (False, [{"returncode":1, "output":"failed"}]))
    result = a.self_repair_apply(_apply_params())
    assert "rolled back" in result.lower()
    assert (tmp_path / "main.py").read_text() == "x = 1\n"


def test_attempt_budget_stops_repair(monkeypatch):
    import actions.self_repair_apply as a
    monkeypatch.setattr(a, "recover_incomplete_transactions", lambda: [])
    params = _apply_params(); params["attempt"] = r.MAX_ATTEMPTS + 1
    assert "attempt budget" in a.self_repair_apply(params).lower()


def test_knowledge_write_failure_rolls_back(monkeypatch, tmp_path):
    import actions.self_repair_apply as a
    _sandbox(monkeypatch, tmp_path); monkeypatch.setattr(a, "BASE_DIR", tmp_path)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(a, "recover_incomplete_transactions", lambda: [])
    monkeypatch.setattr(a, "validate_sandbox", lambda candidates: (True, [{"returncode":0}]))
    monkeypatch.setattr(a, "validate_repository", lambda files: (True, [{"returncode":0}]))
    monkeypatch.setattr(a, "record_knowledge", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    result = a.self_repair_apply(_apply_params())
    assert "rolled back" in result.lower()
    assert (tmp_path / "main.py").read_text() == "x = 1\n"
