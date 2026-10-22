import json
from pathlib import Path

import pytest

from actions import code_helper
from core import action_policy, artifact_paths, script_skills
from core.skill_registry import SkillRegistry


def test_script_and_report_defaults_are_separate(monkeypatch, tmp_path):
    workspace = tmp_path / 'storage/autonomy/workspaces'
    artifacts = tmp_path / 'storage/artifacts'
    monkeypatch.setattr(code_helper, 'WORKSPACE_ROOT', workspace)
    monkeypatch.setattr(code_helper, 'ARTIFACTS', artifacts / 'code')
    monkeypatch.setattr(action_policy, 'WORKSPACE_ROOT', workspace)
    assert code_helper._resolve_save_path('', 'python').parent == workspace
    assert code_helper._resolve_save_path('report.csv', 'python').parent == artifacts / 'code'
    assert not action_policy.requires_confirmation('code_helper', {'action': 'write', 'output_path': 'task.py'})
    assert action_policy.requires_confirmation('code_helper', {'action': 'write', 'output_path': str(workspace / '../../escape.py')})


def test_workspace_script_runs_with_artifact_working_directory(monkeypatch, tmp_path):
    workspace = tmp_path / 'storage/autonomy/workspaces'
    artifacts = tmp_path / 'storage/artifacts'
    workspace.mkdir(parents=True)
    monkeypatch.setattr(artifact_paths, 'WORKSPACE_ROOT', workspace)
    monkeypatch.setattr(code_helper, 'ARTIFACT_ROOT', artifacts)
    source = workspace / 'make.py'
    source.write_text("from pathlib import Path\nPath('report.txt').write_text('done')\n")
    result = json.loads(code_helper._run_file(source, [], 5, True))
    assert result['exit_code'] == 0
    assert (artifacts / 'generated/report.txt').read_text() == 'done'
    assert not (workspace / 'report.txt').exists()


def test_legacy_hash_pinned_script_still_runs_and_tampering_is_rejected(tmp_path):
    import hashlib
    folder = tmp_path / 'storage/artifacts/code/skills'
    folder.mkdir(parents=True)
    source = folder / 'old.py'
    source.write_text('print(42)')
    store = SkillRegistry(tmp_path / 'storage/autonomy')
    record = store.create('legacy', 'Existing task', [{'capability': 'code_helper', 'inputs': {'action': 'run', 'file_path': str(source)}}],
        permissions=('server.script.execute',), risk_level='HIGH',
        provenance={'template': 'approved_script_v1', 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    result = script_skills.run_script_skill(record, tmp_path, {})
    assert result['process_verified'] and '42' in result['output']
    source.write_text('print(99)')
    with pytest.raises(ValueError, match='changed'):
        script_skills.run_script_skill(record, tmp_path, {})


def test_workspace_source_is_observed_without_becoming_a_document(monkeypatch, tmp_path):
    from core.tool_feedback import observed_files, artifact_feedback
    workspace = tmp_path / 'storage/autonomy/workspaces'
    workspace.mkdir(parents=True)
    monkeypatch.setattr(artifact_paths, 'WORKSPACE_ROOT', workspace)
    source = workspace / 'task.py'
    source.write_text('print(42)')
    result = {'verified': True, 'file_path': str(source)}
    assert observed_files(result) == [str(source)]
    assert artifact_feedback('code_helper', result, {'action': 'write'}) == {}
