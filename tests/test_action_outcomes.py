import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from core.action_outcomes import assess
from core import task_continuity as tc


@pytest.mark.parametrize('result,expected', [
    (None, 'UNVERIFIED'), ('Done.', 'UNVERIFIED'),
    ({'ok': True}, 'UNVERIFIED'),
    ({'ok': True, 'status': 'SUCCESS', 'verified': False}, 'UNVERIFIED'),
    ({'verified': True, 'result': {'ok': False}}, 'FAILED'),
    ({'verified': True, 'result': {'status': 'queued'}}, 'WAITING'),
    ({'ok': False, 'verified': True}, 'FAILED'),
    ({'status': 'FAILED'}, 'FAILED'),
    ({'error': 'device failed'}, 'FAILED'),
    ({'executed': False}, 'UNVERIFIED'),
    ({'status': 'queued', 'attachment_id': 'a'}, 'WAITING'),
    ({'status': 'notified', 'attachment_id': 'a'}, 'VERIFIED'),
    ({'status': 'notified'}, 'UNVERIFIED'),
    ({'approval_sent': True}, 'WAITING'),
    ({'verified': True, 'ok': True}, 'VERIFIED'),
    ('File not found: report.pdf', 'FAILED'),
    ('ffmpeg not found.', 'FAILED'),
    ('Pillow is not installed.', 'FAILED'),
    ('Tool run failed: offline', 'FAILED'),
    ('[CONFIRMATION_PENDING] approve', 'WAITING'),
])
def test_outcome_is_conservative_for_dicts_and_json(result, expected):
    assert assess(result) == expected
    if isinstance(result, dict):
        assert assess(json.dumps({'result': json.dumps(result)})) == expected


@pytest.mark.parametrize('result', ['Done.', {'ok': False}, {'status': 'queued'}, {'verified': False}, None])
def test_unverified_or_failed_action_cannot_complete_any_task(tmp_path, monkeypatch, result):
    monkeypatch.setattr(tc, 'STATE_DIR', tmp_path)
    monkeypatch.setattr(tc, 'STATE_FILE', tmp_path / 'active_task.json')
    tc.begin('Perform requested activity')
    tc.action_finished('any_tool', result)
    assert not tc.checkpoint('model claims done', 'model claims evidence')
    assert not tc.complete('claimed complete')


def test_checkpoint_cannot_reuse_same_second_same_tool_result(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, 'STATE_DIR', tmp_path)
    monkeypatch.setattr(tc, 'STATE_FILE', tmp_path / 'active_task.json')
    monkeypatch.setattr(tc, '_now', lambda: 'same-second')
    tc.begin('Perform activity twice')
    tc.action_finished('any_tool', {'verified': True})
    assert tc.checkpoint('first', 'first observed')
    tc.action_finished('any_tool', {'verified': True})
    assert not tc.complete('reuse first checkpoint')


def test_short_text_edits_save_unique_verified_outputs(tmp_path, monkeypatch):
    from actions import file_processor as fp
    from core import artifact_paths
    monkeypatch.setattr(artifact_paths, 'ARTIFACT_ROOT', tmp_path / 'artifacts')
    monkeypatch.setattr(fp, '_gemini_client', lambda: SimpleNamespace(generate_content=lambda prompt: SimpleNamespace(text='Short revised text.')))
    source = tmp_path / 'notes.md'
    source.write_text('Original text.')
    outputs = []
    for _ in range(2):
        result = json.loads(fp.file_processor({'file_path': str(source), 'action': 'fix'}))
        assert result['verified'] and assess(result) == 'VERIFIED'
        output = Path(result['artifacts'][0]['file_path'])
        assert output.read_text() == 'Short revised text.' and output.suffix == '.md'
        outputs.append(output)
    assert outputs[0] != outputs[1] and all(p.exists() for p in outputs)
    assert source.read_text() == 'Original text.'


def test_missing_subprocess_output_is_not_reported_as_success(tmp_path, monkeypatch):
    from actions import file_processor as fp
    from core import artifact_paths
    monkeypatch.setattr(artifact_paths, 'ARTIFACT_ROOT', tmp_path / 'artifacts')
    def fake_handler(path, *args):
        fp._output_path(path, 'converted', '.mp4')
        return 'Converted successfully.'
    monkeypatch.setattr(fp, '_process_video', fake_handler)
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'original')
    result = json.loads(fp.file_processor({'file_path': str(source), 'action': 'convert'}))
    assert result['ok'] is False and assess(result) == 'FAILED'
    assert source.read_bytes() == b'original'


@pytest.mark.parametrize('result,expected', [(None, 'unverified'), ('Done.', 'unverified'), ({'ok': False}, None), ({'status': 'queued'}, 'waiting')])
def test_approval_is_not_execution_verification(monkeypatch, result, expected):
    import threading
    from core import confirm
    monkeypatch.setattr(confirm, '_pending', None)
    finished = threading.Event()
    events = []
    confirm.bind(lambda *a: None, lambda: None,
        on_result=lambda *args: (events.append(args), finished.set()))
    try:
        confirm.request('outcome-test', 'Test', 'Exact arguments', lambda: result)
        confirm.resolve(True, expected_request_id=confirm.pending_request()['request_id'])
        assert finished.wait(2)
        assert events[0][3] is False
        if expected:
            assert events[0][4] == expected
    finally:
        confirm.bind(lambda *a: None, lambda: None)
