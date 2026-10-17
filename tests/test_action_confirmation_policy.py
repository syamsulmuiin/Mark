import threading
import pytest
from core.action_policy import requires_confirmation
from core import confirm


@pytest.mark.parametrize('tool,args', [
    ('runtime_diagnostics', {}), ('self_repair_diagnostic', {'problem': 'debug logs'}),
    ('open_app', {'name': 'Chrome'}), ('browser_control', {'action': 'open', 'url': 'https://example.com'}),
    ('call_current_device', {'capability': 'app.launch', 'args': {'app': 'Chrome'}}),
    ('send_server_file', {'path': 'runtime/error.log'}), ('test_flash_approval', {}),
])
def test_normal_actions_do_not_add_an_outer_confirmation(tool, args):
    assert not requires_confirmation(tool, args)


@pytest.mark.parametrize('tool,args', [
    ('browser_control', {'action': 'execute_script'}),
    ('browser_control', {'action': 'open', 'url': 'javascript:danger()'}),
    ('call_current_device', {'capability': 'open_url', 'args': {'url': 'intent:danger'}}), ('unknown_plugin', {'risk': 'low', 'approved': True}),
    ('call_current_device', {'capability': 'file.delete'}),
    ('call_current_device', {'capability': 'legacy.action', 'args': {'tool': 'delete'}}),
    ('send_server_file', {'save_direct': True}),
])
def test_dangerous_or_unknown_actions_cannot_label_themselves_safe(tool, args):
    assert requires_confirmation(tool, args)


def test_exact_text_proposal_does_not_reprompt_or_execute_twice(monkeypatch):
    monkeypatch.setattr(confirm, '_pending', None)
    monkeypatch.setattr(confirm, '_recent_proposals', {})
    shown, ran = [], []
    done = threading.Event()
    confirm.bind(lambda *a: shown.append(a), lambda: None,
                 on_result=lambda *a: done.set())
    key = 'text_proposal:stable-action-and-origin'
    confirm.request(key, 'Action', 'exact args', lambda: ran.append(1) or 'ok')
    request = confirm.pending_request()
    confirm.resolve(True, expected_request_id=request['request_id'])
    assert done.wait(2)
    result = confirm.request(key, 'Action', 'exact args', lambda: ran.append(2))
    assert result.startswith('[CONFIRMATION_COMPLETED]')
    assert len(shown) == 1 and ran == [1]
    assert confirm.pending_request() is None
    confirm.bind(lambda *_: None, lambda: None)


def test_simple_text_proposal_executes_without_showing_a_dialog(monkeypatch):
    import ast
    import asyncio
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from core import llm_action_proposals
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    methods = [n for n in cls.body if getattr(n, 'name', '') == '_execute_tool']
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
        ast.ClassDef(name='Runtime', bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
    writes = []
    namespace = {'asyncio': asyncio, 'json': json, 'TOOL_DECLARATIONS': [],
                 '_trace_event': lambda *a, **k: None, 'update_memory': writes.append,
                 'types': SimpleNamespace(FunctionResponse=lambda **kw: SimpleNamespace(**kw))}
    exec(compile(ast.fix_missing_locations(module), 'runtime', 'exec'), namespace)
    runtime = namespace['Runtime']()
    runtime.ui = SimpleNamespace(set_state=lambda *_: None, muted=True)
    runtime._dashboard = None
    registry = SimpleNamespace(get_tool_declarations=lambda: [])
    runtime._action_registry = runtime._plugin_registry = registry
    monkeypatch.setattr(llm_action_proposals, 'propose_action', lambda *a: {
        'tool': 'save_memory', 'args': {'key': 'test', 'value': 'value'}, 'executed': False})
    result = asyncio.run(runtime._execute_tool(SimpleNamespace(
        name='propose_text_action', args={'task': 'remember this'}, id='request')))
    assert result.response['result'] == 'ok'
    assert len(writes) == 1
    assert result.name == 'propose_text_action' and result.id == 'request'
