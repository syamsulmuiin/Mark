import json
from types import SimpleNamespace

import pytest

from actions import code_helper
from core.action_outcomes import assess
from core.approval_feedback import speech_instruction
from core.llm_policy import live_delegation_instruction


@pytest.mark.parametrize('exit_code', [0, 3])
def test_general_run_exposes_process_evidence_not_semantic_success(monkeypatch, tmp_path, exit_code):
    source = tmp_path / 'task.py'
    source.write_text('import pathlib\nprint(42)')
    monkeypatch.setattr(code_helper.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=exit_code, stdout='42\n', stderr='diagnostic\n'))
    result = json.loads(code_helper._run_action(str(source), [], 10, None))
    assert result['stdout'] == '42' and result['stderr'] == 'diagnostic'
    assert result['exit_code'] == exit_code
    assert result['process_verified'] is (exit_code == 0)
    assert result['verified'] is False
    assert assess(result) == ('UNVERIFIED' if exit_code == 0 else 'FAILED')
    assert 'read-only tools automatically' in result['instruction']
    assert 'Never rerun side effects' in result['instruction']


def test_routine_checks_are_internal_without_claiming_learning():
    prompt = live_delegation_instruction({'llm_provider': 'deepseek', 'live_provider': 'gemini'})
    assert 'Perform routine result checks automatically' in prompt
    assert 'never claim a correction was learned without persistent evidence' in prompt
    spoken = speech_instruction('unverified')
    assert 'has not been verified' not in spoken
    assert 'does not establish task success' in spoken
