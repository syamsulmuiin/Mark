import json
from pathlib import Path

import pytest
from core.llm_action_proposals import validate_proposal
from core.approval_presentation import present_action, TECHNICAL_MARKER


def test_single_fenced_json_proposal_is_supported():
    raw = json.dumps({'tool': 'open_app', 'args': {'name': 'Chrome'}, 'reason': 'Requested'})
    assert validate_proposal('```json\n' + raw + '\n```', {'open_app'})['tool'] == 'open_app'
    with pytest.raises(ValueError):
        validate_proposal('```json\n' + raw + '\n```\n' + raw, {'open_app'})


def test_approval_has_a_readable_summary_and_all_original_arguments():
    args = {'action': 'write', 'file_path': 'diagnostic_report.txt', 'code': 'Report\nDetails\n' * 300}
    title, detail = present_action('code_helper', args, 'Save the requested diagnostic report')
    summary, technical = detail.split(TECHNICAL_MARKER)
    assert title == 'Create file'
    assert 'diagnostic_report.txt' in summary and 'SHA-256' in summary
    assert 'Report\nDetails' not in summary
    assert json.dumps(args, ensure_ascii=False, indent=2, sort_keys=True) in technical


def test_write_saves_given_report_without_any_llm_and_returns_real_path(monkeypatch, tmp_path):
    from actions import code_helper as helper
    from core import action_policy
    monkeypatch.setattr(helper, 'ARTIFACTS', tmp_path / 'artifacts' / 'code')
    monkeypatch.setattr(helper, 'ARTIFACT_ROOT', tmp_path / 'artifacts')
    monkeypatch.setattr(action_policy, 'ARTIFACT_ROOT', tmp_path / 'artifacts')
    monkeypatch.setattr(helper, '_get_gemini', lambda *a, **kw: pytest.fail('must not regenerate supplied content'))
    args = {'action': 'write', 'file_path': 'diagnostic_report.txt', 'code': 'Exact report\nNo guesses.\n'}
    assert action_policy.requires_confirmation('code_helper', args) is False
    result = json.loads(helper.code_helper(args))
    assert result['ok'] is True and result['verified'] is True
    assert Path(result['file_path']).read_text() == args['code']
    again = json.loads(helper.code_helper({**args, 'code': 'A second report'}))
    assert again['file_path'] != result['file_path']
    assert Path(result['file_path']).read_text() == args['code']
    assert action_policy.requires_confirmation('code_helper', {**args, 'file_path': str(tmp_path / 'outside.txt')}) is True
    assert action_policy.requires_confirmation('code_helper', {**args, 'file_path': '../../escape.txt'}) is True


def test_text_trace_records_deepseek_and_never_credentials_or_prompt(monkeypatch, tmp_path):
    from core import llm_trace, chat_router
    log = tmp_path / 'trace.log'
    monkeypatch.setattr(llm_trace, 'TRACE_LOG', log)
    monkeypatch.setattr(chat_router, 'generate_text', lambda *a, **kw: 'Actual response')
    assert chat_router.generate_chat_text('private prompt', config={
        'llm_provider': 'deepseek', 'chat_models': 'deepseek-chat', 'deepseek_api_key': 'private-key'}) == 'Actual response'
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert [x['stage'] for x in events] == ['started', 'succeeded']
    assert all(x['provider'] == 'deepseek' and x['model'] == 'deepseek-chat' for x in events)
    assert 'private prompt' not in log.read_text() and 'private-key' not in log.read_text()


def _proposal_runtime():
    import ast
    import asyncio
    from types import SimpleNamespace
    tree = __import__('ast').parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    methods = [n for n in cls.body if getattr(n, 'name', '') == '_execute_tool']
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
        ast.ClassDef(name='Runtime', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
    from core import confirm
    events, logs = [], []
    namespace = {'asyncio': asyncio, 'json': json, 'TOOL_DECLARATIONS': [], 'confirm_gate': confirm,
                 '_trace_event': lambda event, **kw: events.append({'event': event, **kw}),
                 'types': SimpleNamespace(FunctionResponse=lambda **kw: SimpleNamespace(**kw))}
    exec(compile(ast.fix_missing_locations(module), 'runtime', 'exec'), namespace)
    runtime = namespace['Runtime']()
    runtime.ui = SimpleNamespace(set_state=lambda *_: None, write_log=logs.append, muted=True)
    runtime._dashboard = None
    runtime._action_registry = runtime._plugin_registry = SimpleNamespace(get_tool_declarations=lambda: [])
    return runtime, events, logs


def test_failed_proposal_cannot_tell_the_user_a_dialog_is_pending(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from core import llm_action_proposals
    runtime, events, logs = _proposal_runtime()
    def invalid(*a):
        raise ValueError('private raw model content must not be logged')
    monkeypatch.setattr(llm_action_proposals, 'propose_action', invalid)
    response = asyncio.run(runtime._execute_tool(SimpleNamespace(
        id='one', name='propose_text_action', args={'task': 'write a file'})))
    assert response.response['approval_sent'] is False
    assert response.response['approval_required'] is False
    assert response.response['failure_stage'] == 'generation'
    assert events[-1]['stage'] == 'failed'
    assert 'private raw model' not in str(logs) + str(response.response)


def test_missing_companion_is_a_delivery_failure_not_a_pending_dialog(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from core import llm_action_proposals, confirm
    runtime, events, logs = _proposal_runtime()
    monkeypatch.setattr(confirm, '_pending', None)
    runtime._dashboard = SimpleNamespace(active_voice_device='phone', _device_sockets={})
    monkeypatch.setattr(llm_action_proposals, 'propose_action', lambda *a: {
        'tool': 'code_helper', 'args': {'action': 'run', 'file_path': 'x.py'},
        'reason': 'Requested execution', 'executed': False})
    response = asyncio.run(runtime._execute_tool(SimpleNamespace(
        id='two', name='propose_text_action', args={'task': 'run x'})))
    assert response.response['approval_sent'] is False
    assert response.response['failure_stage'] == 'review'
    assert confirm.pending_request() is None


def test_blocked_tool_does_not_log_report_body_as_runtime_evidence(capsys):
    import asyncio
    from types import SimpleNamespace
    runtime, events, logs = _proposal_runtime()
    response = asyncio.run(runtime._execute_tool(SimpleNamespace(id='three', name='code_helper', args={
        'action': 'run', 'file_path': 'private-file-name.py', 'code': 'private-report-contents'})))
    output = capsys.readouterr().out
    assert 'private-report-contents' not in output and 'private-file-name' not in output
    assert response.response['approval_sent'] is False
    assert [event['event'] for event in events] == ['tool_requested', 'tool_blocked']


def test_native_confirmation_metadata_requires_a_real_pending_dialog(monkeypatch):
    from core import confirm
    monkeypatch.setattr(confirm, '_pending', None)
    assert confirm.response_metadata('[CONFIRMATION_PENDING] invented')['approval_sent'] is False
    confirm.bind(lambda *a: None, lambda: None)
    message = confirm.request('native-metadata', 'Test', 'Details', lambda: 'done')
    assert confirm.response_metadata(message)['approval_sent'] is True
    confirm.resolve(False, expected_key='native-metadata')
    assert confirm.response_metadata(message)['approval_sent'] is False
