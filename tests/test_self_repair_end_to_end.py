"""Run actual repair subprocess validators against a small disposable repository."""
import json
from pathlib import Path

from core import repair_engine as engine
from core.action_outcomes import assess
from actions import self_repair_apply as apply
from test_self_repair import _sandbox

ROOT = Path(__file__).resolve().parents[1]


def mini_repo(tmp_path, monkeypatch):
    _sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(apply, 'BASE_DIR', tmp_path)
    for folder in ('actions', 'core', 'tests'):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / '__init__.py').write_text('')
    for rel in ('core/repair_engine.py', 'actions/self_repair_apply.py'):
        (tmp_path / rel).write_text((ROOT / rel).read_text())
    (tmp_path / 'actions/self_repair_diagnostic.py').write_text('# import validation fixture\n')
    (tmp_path / 'core/helper.py').write_text('VALUE = 1\nOTHER = 1\n')
    (tmp_path / 'tests/test_helper.py').write_text('from core.helper import VALUE, OTHER\ndef test_fixed():\n    assert VALUE == 2 and OTHER == 2\n')
    return {'apply': True, 'authorization': 'APPLY_DIAGNOSTIC_REPAIR', 'confidence': 'high',
        'risk': 'low', 'operations': [
            {'file': 'core/helper.py', 'old': 'VALUE = 1', 'new': 'VALUE = 2'},
            {'file': 'core/helper.py', 'old': 'OTHER = 1', 'new': 'OTHER = 2'}]}


def test_actual_multi_edit_sandbox_apply_and_postwrite_validators(tmp_path, monkeypatch):
    params = mini_repo(tmp_path, monkeypatch)
    result = json.loads(apply.self_repair_apply(params))
    assert result['source_verified'] is True
    assert result['runtime_verified'] is False
    assert result['activation_required'] == 'restart_server'
    assert assess(result) == 'WAITING'
    assert (tmp_path / 'core/helper.py').read_text() == 'VALUE = 2\nOTHER = 2\n'
    assert all(step['returncode'] == 0 for step in result['validation'])
    tx = engine.TX_DIR / result['transaction_id']
    assert json.loads((tx / 'manifest.json').read_text())['status'] == 'ACCEPTED'
    assert engine.rollback(result['transaction_id']) == ['core/helper.py']
    assert (tmp_path / 'core/helper.py').read_text() == 'VALUE = 1\nOTHER = 1\n'


def test_actual_failing_candidate_never_reaches_production(tmp_path, monkeypatch):
    params = mini_repo(tmp_path, monkeypatch)
    params['operations'][0]['new'] = 'VALUE = 3'
    result = json.loads(apply.self_repair_apply(params))
    assert result['ok'] is False and assess(result) == 'FAILED'
    assert 'sandbox' in result['message']
    assert (tmp_path / 'core/helper.py').read_text() == 'VALUE = 1\nOTHER = 1\n'


def test_missing_validator_reports_install_action(monkeypatch, tmp_path):
    monkeypatch.setattr(engine.importlib.util, 'find_spec', lambda name: None)
    ok, steps = engine._run_validators(tmp_path, [], 1)
    assert ok is False
    assert 'pip install -r requirements.txt' in steps[0]['output']


def test_authorized_diagnosis_applies_once_and_reports_activation_pending(tmp_path, monkeypatch):
    import asyncio
    import re
    from types import SimpleNamespace as NS
    from core import language_compat
    from test_approval_report_regressions import _proposal_runtime
    params = mini_repo(tmp_path, monkeypatch)
    plan_id = 'abcdef123456'
    folder = tmp_path / 'storage/self_repair/plans'
    folder.mkdir(parents=True)
    (folder / (plan_id + '.json')).write_text(json.dumps({**params, 'plan_id': plan_id}))
    runtime, _, _ = _proposal_runtime()
    finished, calls = [], []
    namespace = runtime._execute_tool.__func__.__globals__
    namespace.update(re=re, task_state=NS(action_started=lambda *a: None,
        action_finished=lambda *a: finished.append(a)))
    for name in ('has_explicit_diagnostic_intent', 'is_generic_error_report',
                 'has_explicit_repair_apply_intent', 'has_explicit_high_risk_approval'):
        namespace[name] = getattr(language_compat, name)
    runtime._current_user_transcript = 'Perbaiki nilai helper yang salah'
    runtime._session_log = []
    runtime._last_repair_plan_id = ''
    runtime.speak = lambda *a: None
    async def heartbeat(*args):
        await asyncio.Event().wait()
    runtime._tool_progress_heartbeat = heartbeat
    def run(name, args, context):
        calls.append(name)
        if name == 'self_repair_diagnostic':
            return 'Risk level: low\nRepair plan: ' + plan_id
        return apply.self_repair_apply(args)
    runtime._action_registry.run = run
    response = asyncio.run(runtime._execute_tool(NS(id='repair', name='self_repair_diagnostic',
        args={'problem': 'helper values incorrect'})))
    assert calls == ['self_repair_diagnostic', 'self_repair_apply']
    assert response.response['outcome'] == 'WAITING'
    assert response.response['result']['result']['source_verified'] is True
    assert finished[-1][1]['result']['runtime_verified'] is False
    assert (tmp_path / 'core/helper.py').read_text() == 'VALUE = 2\nOTHER = 2\n'


def test_indonesian_repair_request_is_not_blocked_by_negated_symptom():
    from core.language_compat import has_explicit_diagnostic_intent, has_explicit_repair_apply_intent
    for request in ('Tidak jalan, tolong perbaiki', 'Masih belum berfungsi, perbaiki masalahnya', 'Not working, fix it', 'Lakukan perbaikan ini'):
        assert has_explicit_diagnostic_intent(request)
        assert has_explicit_repair_apply_intent(request)
    for request in ('Jangan perbaiki', 'Tidak usah perbaiki', 'Belum boleh terapkan', 'Do not fix it', "Don't apply the repair", 'Not yet apply the repair', 'Periksa sebelum saya menyetujui perbaikan'):
        assert not has_explicit_repair_apply_intent(request)


def test_source_changed_during_sandbox_is_not_overwritten_or_rolled_back(tmp_path, monkeypatch):
    params = mini_repo(tmp_path, monkeypatch)
    def validate(candidates):
        (tmp_path / 'core/helper.py').write_text('VALUE = 99\nOTHER = 99\n')
        return True, []
    monkeypatch.setattr(apply, 'validate_sandbox', validate)
    result = json.loads(apply.self_repair_apply(params))
    assert result['ok'] is False
    assert (tmp_path / 'core/helper.py').read_text() == 'VALUE = 99\nOTHER = 99\n'
    assert json.loads((engine.TX_DIR / result['transaction_id'] / 'manifest.json').read_text())['status'] == 'REJECTED_STALE'


def test_parallel_repair_does_not_recover_or_overwrite_active_transaction():
    assert apply._REPAIR_LOCK.acquire(blocking=False)
    try:
        result = json.loads(apply.self_repair_apply({}))
        assert result['status'] == 'WAITING'
        assert 'no second repair' in result['message']
    finally:
        apply._REPAIR_LOCK.release()


def test_diagnostic_does_not_save_a_partial_patch_plan(tmp_path, monkeypatch):
    from actions import self_repair_diagnostic as diagnostic
    (tmp_path / 'core').mkdir()
    (tmp_path / 'core/helper.py').write_text('VALUE = 1\n')
    monkeypatch.setattr(diagnostic, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(diagnostic, 'collect_runtime_evidence', lambda **kw: '')
    monkeypatch.setattr(diagnostic, '_source_files', lambda: ['core/helper.py'])
    monkeypatch.setattr(diagnostic, '_discover_files', lambda *a: ['core/helper.py'])
    monkeypatch.setattr(diagnostic, 'search_knowledge', lambda *a, **kw: [])
    monkeypatch.setattr(diagnostic, '_diagnostic_json', lambda *a, **kw: {
        'confidence': 'high', 'files_to_change': ['core/helper.py'], 'risk_level': 'low',
        'operations': [{'file': 'core/helper.py', 'old': 'VALUE = 1', 'new': 'VALUE = 2'},
                       {'file': 'core/helper.py', 'old': 'MISSING = 1', 'new': 'MISSING = 2'}]})
    result = diagnostic.self_repair_diagnostic({'problem': 'repair wrong value'})
    assert 'not generated' in result
    assert not list(tmp_path.rglob('plans/*.json'))
