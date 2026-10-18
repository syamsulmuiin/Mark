import json
from core import interaction_log


def test_event_creates_parent_and_writes_pid(tmp_path):
    path = tmp_path / 'runtime/interaction.log'
    assert interaction_log.write_event(path, 'conversation_entry', chars=12)
    event = json.loads(path.read_text())
    assert event['pid'] > 0 and event['event'] == 'conversation_entry' and event['chars'] == 12


def test_storage_failure_reports_sanitized_rate_limited_error_and_recovers(tmp_path, capsys, monkeypatch):
    parent = tmp_path / 'runtime'
    parent.write_text('not a directory')
    path = parent / 'interaction.log'
    monkeypatch.setattr(interaction_log, '_FAILURES', {})
    assert not interaction_log.write_event(path, 'private-payload', secret='do-not-log')
    first = capsys.readouterr().err
    assert 'Interaction log write failed' in first and 'FileExistsError' in first
    assert 'private-payload' not in first and 'do-not-log' not in first
    assert not interaction_log.write_event(path, 'again')
    assert capsys.readouterr().err == ''
    parent.unlink()
    assert interaction_log.write_event(path, 'recovered')
    path.unlink()
    parent.rmdir()
    parent.write_text('blocked again')
    assert not interaction_log.write_event(path, 'failed-again')
    assert 'Interaction log write failed' in capsys.readouterr().err


def test_text_traces_survive_unwritable_interaction_log(tmp_path, monkeypatch, capsys):
    from core import llm_trace
    parent = tmp_path / 'blocked'
    parent.write_text('not a directory')
    monkeypatch.setattr(llm_trace, 'TRACE_LOG', parent / 'interaction.log')
    assert llm_trace.traced_text_call('openai_codex', 'selected', lambda: 'answer') == 'answer'
    assert 'Interaction log write failed' in capsys.readouterr().err
