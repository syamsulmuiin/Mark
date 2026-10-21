"""Bound diagnostic work and never promote incomplete discovery to a repair plan."""
import json
import pytest
from actions import self_repair_diagnostic as mod


def test_provider_timeout_is_clamped_and_late_result_rejected(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    seen = []
    def provider(*a, **kw):
        seen.append(kw["timeout_ms"])
        clock[0] = 102.0
        return {"root_cause": "late"}
    monkeypatch.setattr(mod.gemini, "as_json", provider)
    token = mod._DIAGNOSTIC_DEADLINE.set(101.0)
    try:
        with pytest.raises(mod.DiagnosticIncomplete):
            mod._diagnostic_json("test", 90000)
        assert seen == [1000]
    finally:
        mod._DIAGNOSTIC_DEADLINE.reset(token)


@pytest.mark.parametrize("selection,limit,reason", [
    (([], False), 32, "source_discovery_stalled"),
    ((["a.py"], False), 1, "source_discovery_round_limit"),
])
def test_incomplete_discovery_is_not_a_complete_diagnosis(monkeypatch, selection, limit, reason):
    monkeypatch.setattr(mod, "MAX_DISCOVERY_ROUNDS", limit)
    monkeypatch.setattr(mod, "_select_files", lambda *a: selection)
    with pytest.raises(mod.DiagnosticIncomplete, match=reason):
        mod._discover_files("bug", ["a.py"])


def test_budget_failure_returns_without_saving_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    def incomplete(*a, **kw):
        raise mod.DiagnosticIncomplete("diagnostic_time_budget_exhausted")
    monkeypatch.setattr(mod, "_diagnose", incomplete)
    result = json.loads(mod.self_repair_diagnostic({"problem":"bug"}))
    assert result["diagnosis_complete"] is False
    assert result["executed"] is False
    assert not (tmp_path / "storage").exists()
    assert mod._DIAGNOSTIC_DEADLINE.get() is None
    assert "repair_diagnostic_incomplete" in (tmp_path / "runtime/interaction.log").read_text()


def test_provider_failure_after_deadline_is_incomplete_not_unavailable(monkeypatch, tmp_path):
    clock = [100.0]
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    def provider(*a, **kw):
        clock[0] = 146.0
        raise RuntimeError("private provider response")
    monkeypatch.setattr(mod.gemini, "as_json", provider)
    monkeypatch.setattr(mod, "_diagnose", lambda *a, **kw: mod._diagnostic_json("test", 60000))
    result = json.loads(mod.self_repair_diagnostic({"problem":"bug"}))
    assert result["reason"] == "diagnostic_time_budget_exhausted"
    events = (tmp_path / "runtime/interaction.log").read_text()
    assert "repair_diagnostic_incomplete" in events
    assert "repair_diagnostic_returned" not in events
    assert "private provider response" not in events


def test_early_provider_failure_has_explicit_failure_event(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    def fail(*a, **kw):
        raise mod.DiagnosticModelUnavailable("ConnectionError")
    monkeypatch.setattr(mod, "_diagnose", fail)
    result = json.loads(mod.self_repair_diagnostic({"problem":"bug"}))
    assert result["status"] == "FAILED"
    assert result["diagnosis_complete"] is False
    events = (tmp_path / "runtime/interaction.log").read_text()
    assert "repair_diagnostic_failed" in events
    assert "repair_diagnostic_returned" not in events
    assert not (tmp_path / "storage").exists()


def test_source_ranking_keeps_all_candidates_and_prefers_explicit_evidence():
    files = ["docs/setup.md", "core/llm_text.py", "actions/self_repair_diagnostic.py", "main.py"]
    ranked = mod._prioritize_sources('Failure in actions/self_repair_diagnostic.py', files)
    assert ranked[0] == "actions/self_repair_diagnostic.py"
    assert set(ranked) == set(files)
    assert mod._prioritize_sources('../../secrets.py', files) == sorted(files)
