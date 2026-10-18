import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from core import setup_config, chat_router, llm_anthropic, reasoning, text_commands


def test_repeated_setup_preserves_provider_key_and_model(tmp_path, monkeypatch):
    path = tmp_path / 'keys.json'
    path.write_text(json.dumps({'llm_provider': 'anthropic', 'chat_models': 'claude-test',
                                'anthropic_api_key': 'secret', 'gemini_api_key': 'voice'}))
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    answers = iter(['', '', '', ''])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda _: pytest.fail('key already saved'))
    assert setup_config.interactive_llm_setup()
    saved = json.loads(path.read_text())
    assert saved['llm_provider'] == 'anthropic'
    assert saved['chat_models'] == 'claude-test'
    assert saved['anthropic_api_key'] == 'secret'


def test_switching_providers_keeps_separate_models(tmp_path, monkeypatch):
    path = tmp_path / 'keys.json'
    path.write_text('{}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    setup_config.save_llm_selection('openai', chat_models='gpt-test')
    setup_config.save_llm_selection('anthropic', chat_models='claude-test')
    saved = setup_config.save_llm_selection('openai')
    assert saved['chat_models'] == 'gpt-test'
    assert saved['provider_models']['anthropic'] == 'claude-test'
    saved = setup_config.save_llm_selection('deepseek')
    assert 'chat_models' not in saved


def test_claude_transport_contract(monkeypatch):
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            return json.dumps({'content': [{'type': 'text', 'text': 'Halo'}],
                               'stop_reason': 'end_turn'}).encode()
    def transport(request, timeout):
        captured.update(url=request.full_url, headers=dict(request.header_items()),
                        body=json.loads(request.data), timeout=timeout)
        return Response()
    monkeypatch.setattr(llm_anthropic, 'urlopen', transport)
    assert llm_anthropic.generate_text('claude-test', 'hello', api_key='secret') == 'Halo'
    assert captured['url'] == 'https://api.anthropic.com/v1/messages'
    assert captured['headers']['X-api-key'] == 'secret'
    assert captured['headers']['Anthropic-version'] == '2023-06-01'
    assert captured['body']['max_tokens'] > 0
    assert captured['body']['messages'] == [{'role': 'user', 'content': 'hello'}]
    with pytest.raises(ValueError):
        llm_anthropic.generate_text('claude-test', 'hello')


def test_claude_router_never_uses_compatible_or_gemini(monkeypatch):
    monkeypatch.setattr(chat_router, 'generate_text', lambda *a, **k: pytest.fail('wrong provider'))
    calls = []
    monkeypatch.setattr(chat_router, 'generate_claude_text',
                        lambda *a, **k: calls.append((a, k)) or 'OK')
    assert chat_router.generate_chat_text('hello', config={
        'llm_provider': 'anthropic', 'anthropic_api_key': 'key',
        'chat_models': 'stale', 'provider_models': {'anthropic': 'claude-test'},
    }) == 'OK'
    assert calls == [(('claude-test', 'hello'), {'api_key': 'key'})]


def test_reasoning_helpers_follow_provider_and_preserve_deadline(monkeypatch):
    monkeypatch.setattr(reasoning, 'load_config', lambda: {'llm_provider': 'openai'})
    monkeypatch.setattr(reasoning.gemini, 'call', lambda *a, **k: pytest.fail('Gemini called'))
    calls = []
    monkeypatch.setattr(reasoning, 'generate', lambda *a, **k: calls.append((a, k)) or '{"ok":true}')
    assert reasoning.as_json('test', config={'system_instruction': 'policy'}, timeout_ms=45000) == {'ok': True}
    assert calls[0][0][0] == 'policy\n\ntest'
    assert calls[0][1]['timeout'] == 45
    with pytest.raises(ValueError):
        reasoning.call([object()])


def _runtime_type():
    source = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    methods = [n for n in cls.body if getattr(n, 'name', '') == '_route_text_command']
    module = ast.Module(body=[ast.ClassDef(name='Runtime', bases=[], keywords=[], body=methods,
                                        decorator_list=[])], type_ignores=[])
    namespace = {'asyncio': asyncio, '_trace_event': lambda *a, **k: None}
    exec(compile(ast.fix_missing_locations(module), 'runtime', 'exec'), namespace)
    return namespace['Runtime']


@pytest.mark.parametrize('fails', [False, True])
@pytest.mark.parametrize('provider', ['openai', 'deepseek', 'gemini'])
def test_typed_runtime_bypasses_live_even_on_provider_failure(monkeypatch, fails, provider):
    monkeypatch.setattr(setup_config, 'load_config', lambda: {'llm_provider': provider, 'live_provider': 'gemini'})
    calls, entries = [], []
    def respond(text, **kwargs):
        calls.append(text)
        if fails: raise RuntimeError('private provider payload')
        return 'provider answer'
    monkeypatch.setattr(text_commands, 'respond', respond)
    runtime = _runtime_type()()
    async def forbidden(**kwargs): pytest.fail('Live must not receive typed request')
    runtime.session = SimpleNamespace(send_client_content=forbidden)
    runtime._session_log = []
    runtime._record_transcript_entry = lambda speaker, text: entries.append((speaker, text))
    logs = []
    runtime.ui = SimpleNamespace(write_log=logs.append)
    asyncio.run(runtime._route_text_command('hello'))
    assert calls == ['hello']
    assert entries[0] == ('user', 'hello')
    assert entries[-1][0] == 'jarvis'
    assert 'private provider payload' not in str(logs)
    if not fails: assert entries[-1][1] == 'provider answer'
