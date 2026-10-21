import json
import pytest
from core.diagnostic_progress import DiagnosticProgress
from actions import self_repair_diagnostic as mod


def test_progress_is_private_scoped_and_invalidated_by_actual_source(tmp_path):
    (tmp_path / 'a.py').write_text('value=1')
    progress = DiagnosticProgress(tmp_path, 'problem', ['a.py'])
    progress.save(['a.py'], False)
    assert progress.load() == (['a.py'], False)
    assert progress.path.stat().st_mode & 0o077 == 0
    assert DiagnosticProgress(tmp_path, 'other problem', ['a.py']).load() == ([], False)
    (tmp_path / 'a.py').write_text('value=2')
    assert DiagnosticProgress(tmp_path, 'problem', ['a.py']).load() == ([], False)


def test_expired_or_invalid_paths_are_ignored(tmp_path):
    (tmp_path / 'a.py').write_text('pass')
    progress = DiagnosticProgress(tmp_path, 'problem', ['a.py'])
    progress.save(['a.py'], False)
    data = json.loads(progress.path.read_text())
    data['updated_at'] = 0
    progress.path.write_text(json.dumps(data))
    assert progress.load() == ([], False)
    progress.save(['../../secret'], False)
    assert progress.load() == ([], False)


def test_explicit_second_diagnosis_resumes_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'BASE_DIR', tmp_path)
    for name in ['a.py', 'b.py']:
        (tmp_path / name).write_text('pass')
    token = mod._DIAGNOSTIC_SCOPE.set('same symptom')
    try:
        monkeypatch.setattr(mod, 'MAX_DISCOVERY_ROUNDS', 1)
        monkeypatch.setattr(mod, '_select_files', lambda *a: (['a.py'], False))
        with pytest.raises(mod.DiagnosticIncomplete):
            mod._discover_files('evidence version 1', ['a.py', 'b.py'])
        def select(problem, files, inspected):
            assert inspected == ['a.py']
            return ['b.py'], True
        monkeypatch.setattr(mod, '_select_files', select)
        assert mod._discover_files('growing runtime log', ['a.py', 'b.py']) == ['a.py', 'b.py']
        monkeypatch.setattr(mod, '_select_files', lambda *a: pytest.fail('completed discovery replayed'))
        assert mod._discover_files('new runtime evidence', ['a.py', 'b.py']) == ['a.py', 'b.py']
    finally:
        mod._DIAGNOSTIC_SCOPE.reset(token)


def test_progress_directory_symlink_is_rejected(tmp_path):
    (tmp_path / 'a.py').write_text('pass')
    other = tmp_path / 'outside'
    other.mkdir()
    (tmp_path / 'storage').symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError):
        DiagnosticProgress(tmp_path, 'problem', ['a.py'])
