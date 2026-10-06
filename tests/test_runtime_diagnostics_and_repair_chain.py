from pathlib import Path
import importlib

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_diagnostics_reads_only_fixed_runtime_logs(monkeypatch, tmp_path):
    mod = importlib.import_module("actions.runtime_diagnostics")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "error.log").write_text("[WARN] failed token=supersecret\nnext error\n", encoding="utf-8")
    (runtime / "interaction.log").write_text('{"event":"runtime_error","error":"deadline","token":"jsonsecret"}\n', encoding="utf-8")
    monkeypatch.setattr(mod, "RUNTIME_DIR", runtime)
    text = mod.collect_runtime_evidence("all", 20)
    assert "runtime/error.log" in text
    assert "runtime/interaction.log" in text
    assert "supersecret" not in text
    assert "jsonsecret" not in text
    assert "<redacted>" in text


def test_runtime_diagnostics_uses_rotated_error_when_current_missing(monkeypatch, tmp_path):
    mod = importlib.import_module("actions.runtime_diagnostics")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "error.log.1").write_text("[ERROR] startup failed\n", encoding="utf-8")
    monkeypatch.setattr(mod, "RUNTIME_DIR", runtime)
    text = mod.collect_runtime_evidence("error", 20)
    assert "runtime/error.log.1" in text
    assert "startup failed" in text


def test_diagnostic_plan_path_uses_project_base_not_undefined_root(monkeypatch, tmp_path):
    mod = importlib.import_module("actions.self_repair_diagnostic")
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    assert mod._plan_dir() == tmp_path / "storage" / "self_repair" / "plans"
    assert mod._plan_dir().is_dir()


def test_server_registry_exposes_runtime_diagnostics():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert '"runtime_diagnostics"' in src
    assert '"authorization": "APPLY_DIAGNOSTIC_REPAIR"' in src
    assert "SELF-REPAIR APPLY RESULT" in src
    assert "explicit high-risk approval is required" in src


def test_prompt_no_longer_claims_apply_tool_does_not_exist():
    prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")
    assert "There is currently no tool that authorizes applying a self-repair" not in prompt
    assert "guarded transactional self_repair_apply" in prompt


def test_diagnostic_uses_live_fallback_only_after_rest_quota(monkeypatch):
    mod = importlib.import_module("actions.self_repair_diagnostic")
    calls = []

    def fake_as_json(prompt, tier, timeout_ms, default):
        calls.append(tier)
        return {} if tier == mod.gemini.SMART else {"ok": True}

    monkeypatch.setattr(mod.gemini, "as_json", fake_as_json)
    monkeypatch.setattr(mod.gemini, "last_call_errors", lambda: (("m", "429 RESOURCE_EXHAUSTED"),))
    assert mod._diagnostic_json("x", 10000) == {"ok": True}
    assert calls == [mod.gemini.SMART, mod.gemini.LIVE]


def test_all_rest_text_models_in_cooldown_are_not_retried(monkeypatch):
    gemini = importlib.import_module("core.gemini")
    old = gemini._LADDERS[gemini.FAST]
    gemini._LADDERS[gemini.FAST] = ("one", "two")
    try:
        gemini._cooldown.clear()
        gemini._cool("one", seconds=300)
        gemini._cool("two", seconds=300)
        monkeypatch.setattr(gemini, "api_key", lambda refresh=False: "test-key")
        monkeypatch.setattr(gemini, "client", lambda **_: (_ for _ in ()).throw(AssertionError("client must not be called")))
        assert gemini.call("hello", tier=gemini.FAST) is None
        assert gemini.last_call_errors() == (("one", "cooldown"), ("two", "cooldown"))
    finally:
        gemini._LADDERS[gemini.FAST] = old
        gemini._cooldown.clear()
