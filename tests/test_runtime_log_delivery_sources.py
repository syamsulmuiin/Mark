"""Diagnostics must distinguish real attachment sources from an inspection."""
import json
from actions import runtime_diagnostics as mod


def sources(report):
    return json.loads(report.split("Log attachment sources (JSON):\n", 1)[1].split("\n", 1)[0])


def test_existing_logs_offer_current_device_attachment_handoff(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "RUNTIME_DIR", tmp_path)
    (tmp_path / "error.log").write_text("warning")
    (tmp_path / "interaction.log").write_text('{"event":"tool_started"}')
    report = mod.collect_runtime_evidence()
    assert sources(report) == [
        {"source": str(tmp_path / name), "destination_name": name}
        for name in ("error.log", "interaction.log")]
    assert "has not sent any file" in report
    assert "destination_device=current" in report
    assert "save_direct=false" in report


def test_missing_or_symlinked_logs_are_not_attachment_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "RUNTIME_DIR", tmp_path)
    secret = tmp_path / "private.txt"
    secret.write_text("private")
    (tmp_path / "error.log").symlink_to(secret)
    assert sources(mod.collect_runtime_evidence()) == []


def test_scope_does_not_offer_an_unrequested_log(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "RUNTIME_DIR", tmp_path)
    for name in ("error.log", "interaction.log"):
        (tmp_path / name).write_text("entry")
    assert [x["destination_name"] for x in sources(mod.collect_runtime_evidence("error"))] == ["error.log"]


def test_collection_verifies_reads_not_health_or_log_contents(monkeypatch, tmp_path):
    from core.action_outcomes import assess
    monkeypatch.setattr(mod, 'RUNTIME_DIR', tmp_path)
    (tmp_path / 'error.log').write_text('FAILED: token=private-value')
    result = json.loads(mod.runtime_diagnostics({'scope': 'error'}))
    assert assess(result) == 'VERIFIED'
    assert result['reads'][0]['bytes_read'] > 0
    assert result['verification_scope'] == 'bounded_server_log_collection_only'
    assert 'private-value' not in result['report']


def test_missing_and_failed_reads_never_verify(monkeypatch, tmp_path):
    from core.action_outcomes import assess
    monkeypatch.setattr(mod, 'RUNTIME_DIR', tmp_path)
    assert assess(mod.runtime_diagnostics({})) == 'UNVERIFIED'
    (tmp_path / 'error.log').write_text('entry')
    original = mod.Path.open
    def denied(path, *args, **kwargs):
        if path.name == 'error.log':
            raise PermissionError('private failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(mod.Path, 'open', denied)
    result = json.loads(mod.runtime_diagnostics({'scope': 'error'}))
    assert assess(result) == 'FAILED'
    assert result['reads'][0]['error_type'] == 'PermissionError'
    assert 'private failure' not in json.dumps(result)


def test_rotated_read_and_empty_current_log_are_valid_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'RUNTIME_DIR', tmp_path)
    (tmp_path / 'error.log.1').write_text('old warning')
    result = json.loads(mod.runtime_diagnostics({'scope': 'error'}))
    assert result['verified'] is True
    (tmp_path / 'error.log').write_text('')
    result = json.loads(mod.runtime_diagnostics({'scope': 'error'}))
    assert result['verified'] is True
    assert result['reads'][0]['bytes_read'] == 0
