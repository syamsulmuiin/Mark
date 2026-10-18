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


def test_diagnostic_never_falls_back_to_live(monkeypatch):
    mod = importlib.import_module("actions.self_repair_diagnostic")
    calls = []
    def fake_as_json(prompt, tier, timeout_ms, default):
        calls.append(tier)
        return {}
    monkeypatch.setattr(mod.gemini, "as_json", fake_as_json)
    assert mod._diagnostic_json("x", 10000) == {}
    assert calls == [mod.gemini.SMART]


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
        assert gemini.last_call_errors() == (("one", "cooldown"),)
    finally:
        gemini._LADDERS[gemini.FAST] = old
        gemini._cooldown.clear()


def test_log_diagnosis_keeps_errors_when_audio_floods_the_tail(monkeypatch, tmp_path):
    mod = importlib.import_module('actions.runtime_diagnostics')
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    import json
    rows = [{'event': 'tool_started', 'tool': 'runtime_diagnostics'},
            {'event': 'runtime_error', 'error': 'connection failed'}]
    rows += [{'event': 'audio_in', 'bytes': 1024}] * 400
    (runtime / 'interaction.log').write_text('\n'.join(json.dumps(row) for row in rows))
    monkeypatch.setattr(mod, 'RUNTIME_DIR', runtime)
    text = mod.collect_runtime_evidence('interaction', 20)
    assert 'connection failed' in text and 'tool_started' in text
    assert 'audio_in' not in text
    assert 'entries may include older runs' in text


def test_discovery_sees_dependency_contents_and_skips_generated_data(monkeypatch, tmp_path):
    mod = importlib.import_module('actions.self_repair_diagnostic')
    (tmp_path / 'main.py').write_text('from core import dependency\n')
    (tmp_path / 'core').mkdir()
    (tmp_path / 'core/dependency.py').write_text('VALUE = 1\n')
    (tmp_path / 'core/confirm.py').write_text('# protected but inspectable\n')
    (tmp_path / 'storage').mkdir()
    (tmp_path / 'storage/noise.txt').write_text('generated data')
    monkeypatch.setattr(mod, 'BASE_DIR', tmp_path)
    prompts = []
    def fake(prompt, timeout_ms):
        prompts.append(prompt)
        return {'files': ['core/dependency.py'], 'closure_complete': True}
    monkeypatch.setattr(mod, '_diagnostic_json', fake)
    files = mod._source_files()
    assert 'storage/noise.txt' not in files
    assert 'core/confirm.py' in files
    mod._select_files('diagnose', files, ['main.py'])
    assert 'from core import dependency' in prompts[0]


def test_diagnosis_provider_failure_is_bounded_and_does_not_leak_exception(monkeypatch):
    mod = importlib.import_module('actions.self_repair_diagnostic')
    monkeypatch.setattr(mod, 'collect_runtime_evidence', lambda **kw: '')
    monkeypatch.setattr(mod, '_source_files', lambda: ['main.py'])
    def fail(*a, **kw):
        raise RuntimeError('private-api-key=do-not-show')
    monkeypatch.setattr(mod.gemini, 'as_json', fail)
    result = mod.self_repair_diagnostic({'problem': 'diagnose repeated confirmations'})
    assert 'Diagnosis unavailable' in result and 'No repair was performed' in result
    assert 'do-not-show' not in result
    assert 'do not repeat' in result


def test_missing_and_empty_logs_are_distinct(monkeypatch, tmp_path):
    from actions import runtime_diagnostics as mod
    monkeypatch.setattr(mod, 'RUNTIME_DIR', tmp_path)
    (tmp_path / 'error.log').write_text('')
    report = mod.collect_runtime_evidence()
    assert 'error.log: present, 0 bytes' in report
    assert 'interaction.log: missing' in report
    assert 'does not prove absence' in report


def test_diagnostics_finds_conversation_after_more_than_old_tail_limit(monkeypatch, tmp_path):
    import json
    from actions import runtime_diagnostics as mod
    rows = [{'event': 'conversation_entry', 'speaker': 'jarvis', 'chars': 32, 'partial': False}]
    rows += [{'event': 'audio_to_gemini', 'bytes': 1024}] * 5000
    path = tmp_path / 'interaction.log'
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    assert path.stat().st_size > mod._MAX_BYTES
    monkeypatch.setattr(mod, 'RUNTIME_DIR', tmp_path)
    report = mod.collect_runtime_evidence('interaction')
    assert 'conversation_entry' in report and 'audio_to_gemini' not in report


def test_recording_transcript_emits_payload_free_event():
    import ast
    from types import SimpleNamespace
    tree = ast.parse((ROOT / 'main.py').read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_record_transcript_entry')
    namespace = {'_clean_transcript': lambda value: value.strip(), '_trace_event': lambda event, **fields: events.append((event, fields))}
    events = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<recording>', 'exec'), namespace)
    runtime = SimpleNamespace(_asst_name='Jarvis', ui=SimpleNamespace(write_log=lambda text: None), _session_log=[], _dashboard=None)
    namespace['_record_transcript_entry'](runtime, 'jarvis', 'private conversation', partial=True)
    assert events == [('conversation_entry', {'speaker': 'jarvis', 'chars': 20, 'partial': True})]
    assert 'private conversation' not in str(events)
