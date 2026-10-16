"""Skill health should reflect recent reliability, without bypassing review."""
from core.skill_registry import SkillRegistry


def _verified_skill(tmp_path):
    store = SkillRegistry(tmp_path)
    skill = store.create("safe", "pure operation", [], skill_type="GENERATED")
    store.promote(skill["skill_id"], "CANDIDATE", "static validation")
    store.promote(skill["skill_id"], "VERIFIED", "functional tests")
    return store, skill["skill_id"]


def test_consecutive_failures_degrade_then_quarantine(tmp_path):
    store, sid = _verified_skill(tmp_path)
    for _ in range(3):
        store.record(sid, False, failure="runtime_error")
    assert store.get(sid)["operational_state"] == "DEGRADED"
    for _ in range(2):
        store.record(sid, False, failure="runtime_error")
    assert store.get(sid)["operational_state"] == "QUARANTINED"
    assert store.get(sid)["metrics"]["consecutive_failures"] == 5
    store.record(sid, True)
    assert store.get(sid)["operational_state"] == "QUARANTINED"


def test_success_resets_failure_streak(tmp_path):
    store, sid = _verified_skill(tmp_path)
    for _ in range(4):
        store.record(sid, False, failure="temporary")
    store.record(sid, True)
    for _ in range(4):
        store.record(sid, False, failure="temporary")
    assert store.get(sid)["metrics"]["consecutive_failures"] == 4
    assert store.get(sid)["operational_state"] == "DEGRADED"


def test_disabled_skill_not_activated_by_recording(tmp_path):
    store, sid = _verified_skill(tmp_path)
    store.set_operational_state(sid, "DISABLED", "owner choice")
    for _ in range(5):
        store.record(sid, False, failure="offline")
    assert store.get(sid)["operational_state"] == "DISABLED"
