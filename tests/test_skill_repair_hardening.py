"""Regression tests for skill storage boundaries and interrupted repair recovery."""
import json

import pytest

from core.dynamic_skill_registry import DynamicSkillRegistry
from core import repair_engine


@pytest.mark.parametrize("skill_id", ["../escape", "/absolute", ".", "..", "x/y", "x\\\\y", ""])
def test_generated_skill_ids_cannot_escape_storage(tmp_path, skill_id):
    registry = DynamicSkillRegistry(tmp_path, skills=None)
    with pytest.raises(ValueError, match="invalid_skill_id"):
        registry._dir(skill_id)


def test_prepared_repair_recovery_does_not_overwrite_later_changes(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "example.py"
    source.write_text("original", encoding="utf-8")
    monkeypatch.setattr(repair_engine, "BASE_DIR", repo)
    monkeypatch.setattr(repair_engine, "STATE_DIR", repo / "storage" / "self_repair")
    monkeypatch.setattr(repair_engine, "TX_DIR", repo / "storage" / "self_repair" / "transactions")
    monkeypatch.setattr(repair_engine, "AUDIT_FILE", repo / "storage" / "self_repair" / "audit.jsonl")
    txid = repair_engine.begin_transaction("test", "low", {"example.py": "original"}, [])
    source.write_text("later user edit", encoding="utf-8")
    assert repair_engine.recover_incomplete_transactions() == [txid]
    assert source.read_text(encoding="utf-8") == "later user edit"
    manifest = json.loads((repair_engine.TX_DIR / txid / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "ROLLED_BACK"


def test_written_repair_recovery_restores_snapshot(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "example.py"
    source.write_text("original", encoding="utf-8")
    monkeypatch.setattr(repair_engine, "BASE_DIR", repo)
    monkeypatch.setattr(repair_engine, "STATE_DIR", repo / "storage" / "self_repair")
    monkeypatch.setattr(repair_engine, "TX_DIR", repo / "storage" / "self_repair" / "transactions")
    monkeypatch.setattr(repair_engine, "AUDIT_FILE", repo / "storage" / "self_repair" / "audit.jsonl")
    txid = repair_engine.begin_transaction("test", "low", {"example.py": "original"}, [])
    repair_engine.set_status(txid, "CANDIDATE_WRITTEN")
    source.write_text("candidate", encoding="utf-8")
    assert repair_engine.recover_incomplete_transactions() == [txid]
    assert source.read_text(encoding="utf-8") == "original"
