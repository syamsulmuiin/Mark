import json

import pytest
from core import setup_config, chat_router, llm_codex


@pytest.mark.parametrize('index,row', list(enumerate(setup_config.CHAT_PROVIDER_CATALOG, 1)))
def test_every_displayed_text_provider_number_and_id_resolve(index, row):
    key, _, ready = row
    assert ready
    for choice in (str(index), key, ' ' + str(index) + ' '):
        assert setup_config._resolve_provider_choice(choice, '1', setup_config.CHAT_PROVIDER_CATALOG) == key


def test_codex_menu_selection_login_save_and_runtime_route(tmp_path, monkeypatch):
    path = tmp_path / 'keys.json'
    path.write_text(json.dumps({'llm_provider': 'deepseek', 'gemini_api_key': 'live-key',
                               'chat_models': 'deepseek-chat'}))
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    answers = iter(['3', '1', '1', ''])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda _: pytest.fail('Codex account mode must not request API key'))
    from core import provider_credentials
    monkeypatch.setattr(provider_credentials, 'ROOT', tmp_path / 'auth')
    provider_credentials.save('openai_codex', {'access_token': 'account-token', 'refresh_token': 'refresh',
        'account_id': 'acct', 'expires_at': 1e12})
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self):
            yield b'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"Codex answer"}]}]}}\n'
    def request(request, **kwargs):
        calls.append(json.loads(request.data))
        return Response()
    monkeypatch.setattr(llm_codex, 'urlopen', request)
    monkeypatch.setattr(chat_router, 'generate_text', lambda *a, **k: pytest.fail('no fallback'))
    monkeypatch.setattr(chat_router, 'generate_claude_text', lambda *a, **k: pytest.fail('no fallback'))
    assert setup_config.interactive_llm_setup()
    saved = setup_config.load_config()
    assert saved['llm_provider'] == 'openai_codex'
    assert saved['live_provider'] == 'gemini' and saved['gemini_api_key'] == 'live-key'
    assert saved['provider_models']['openai_codex'] == 'account-model'
    assert saved['provider_models']['deepseek'] == 'deepseek-chat'
    assert 'openai_codex_api_key' not in saved
    assert chat_router.generate_chat_text('test', config=saved) == 'Codex answer'
    assert calls[-1]['model'] == 'account-model'


def test_codex_failed_login_preserves_configuration(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'keys.json'
    path.write_text('{"gemini_api_key":"live-key","llm_provider":"deepseek"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    answers = iter(['3', '1'])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    from core import provider_credentials
    monkeypatch.setattr(provider_credentials, 'ROOT', tmp_path / 'auth')
    monkeypatch.setattr(llm_codex, 'login', lambda: (_ for _ in ()).throw(RuntimeError('OpenAI account login cancelled; run Mark setup again')))
    before = path.read_bytes()
    assert not setup_config.interactive_llm_setup()
    assert path.read_bytes() == before
    output = capsys.readouterr().out
    assert 'OpenAI account login cancelled' in output and 'not implemented' not in output


def test_invalid_menu_choice_is_not_reported_as_missing_adapter():
    with pytest.raises(ValueError, match='Unknown provider selection'):
        setup_config._resolve_provider_choice('99', '1', setup_config.CHAT_PROVIDER_CATALOG)
    assert setup_config._resolve_provider_choice('', '3', setup_config.CHAT_PROVIDER_CATALOG) == 'openai_codex'


def test_text_stage_finishes_before_live_menu_is_printed(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'keys.json'
    path.write_text('{"gemini_api_key":"live-key"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    before = path.read_bytes()
    answers = iter(['2', 'text-model', '1', ''])
    prompts = []
    def answer(prompt):
        output = capsys.readouterr().out
        prompts.append(prompt)
        if len(prompts) <= 2:
            assert 'STEP 2/2' not in output and 'Gemini Live' not in output
        elif len(prompts) == 3:
            assert 'STEP 2/2' in output and 'Gemini Live' in output
        assert path.read_bytes() == before
        return next(answers)
    def key(prompt):
        assert len(prompts) == 1
        assert 'STEP 2/2' not in capsys.readouterr().out
        return 'text-key'
    monkeypatch.setattr(setup_config, '_safe_input', answer)
    monkeypatch.setattr(setup_config.getpass, 'getpass', key)
    assert setup_config.interactive_llm_setup()
    assert ['Chat / reasoning provider', 'text model ID', 'Live / voice provider', 'Live audio model'] == [
        next(label for label in ['Chat / reasoning provider', 'text model ID', 'Live / voice provider', 'Live audio model'] if label in prompt) for prompt in prompts]


def test_cancelling_live_stage_does_not_save_partial_text_settings(tmp_path, monkeypatch):
    path = tmp_path / 'keys.json'
    path.write_text('{"gemini_api_key":"live-key","llm_provider":"gemini"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    answers = iter(['2', 'text-model'])
    def answer(prompt):
        if 'Live / voice provider' in prompt:
            raise EOFError
        return next(answers)
    monkeypatch.setattr(setup_config, '_safe_input', answer)
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda _: 'text-key')
    before = path.read_bytes()
    assert not setup_config.interactive_llm_setup()
    assert path.read_bytes() == before


@pytest.mark.parametrize('provider,extra,model', [('google_oauth', [], 'google-model'), ('openrouter', ['2'], 'router-model')])
def test_native_login_setup_keeps_text_and_live_independent(tmp_path, monkeypatch, provider, extra, model):
    from core import provider_credentials, llm_google_oauth, provider_oauth
    monkeypatch.setattr(provider_credentials, 'ROOT', tmp_path / 'auth')
    path = tmp_path / 'keys.json'
    path.write_text('{"gemini_api_key":"voice-key"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    calls = []
    monkeypatch.setattr(llm_google_oauth, 'login', lambda *a: calls.append('google-login'))
    monkeypatch.setattr(llm_google_oauth, 'credentials', lambda: ('creds', 'project'))
    monkeypatch.setattr(provider_oauth, 'openrouter_login', lambda *a: calls.append('router-login') or 'router-key')
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda _: pytest.fail('native login must not ask for API key'))
    answers = iter([provider, *extra, model, '1', ''])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    assert setup_config.interactive_llm_setup()
    saved = setup_config.load_config()
    assert saved['llm_provider'] == provider and saved['live_provider'] == 'gemini'
    assert saved['gemini_api_key'] == 'voice-key' and saved['provider_models'][provider] == model
    assert calls == ['google-login' if provider == 'google_oauth' else 'router-login']
    if provider == 'openrouter': assert saved['openrouter_api_key'] == 'router-key'


def test_browser_login_is_an_explicit_setup_choice(tmp_path, monkeypatch):
    from core import provider_credentials
    monkeypatch.setattr(provider_credentials, 'ROOT', tmp_path / 'auth')
    path = tmp_path / 'keys.json'
    path.write_text('{"gemini_api_key":"voice-key"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    answers = iter(['3', '2', 'account-model', '1', ''])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    monkeypatch.setattr(llm_codex, 'login', lambda *a: pytest.fail('must not try device auth'))
    def login(read_secret):
        provider_credentials.save('openai_codex', {'access_token': 'token', 'refresh_token': 'refresh', 'account_id': 'account', 'expires_at': 1e12})
    monkeypatch.setattr(llm_codex, 'login_browser', login)
    assert setup_config.interactive_llm_setup()
    assert setup_config.load_config()['llm_provider'] == 'openai_codex'


def test_reported_530_stops_setup_before_model_and_live_without_changing_config(tmp_path, monkeypatch, capsys):
    import io
    from urllib.error import HTTPError
    from core import provider_credentials, provider_oauth
    monkeypatch.setattr(provider_credentials, 'ROOT', tmp_path / 'auth')
    path = tmp_path / 'keys.json'
    path.write_text('{"gemini_api_key":"voice-key","llm_provider":"deepseek"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    before = path.read_bytes()
    answers = iter(['3', '1'])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    calls = []
    def request(req, **kw):
        calls.append(req.full_url)
        raise HTTPError(req.full_url, 530, 'private-body', {'Server': 'cloudflare'}, io.BytesIO(b'error code: 1016 private-token'))
    monkeypatch.setattr(provider_oauth, 'urlopen', request)
    assert not setup_config.interactive_llm_setup()
    assert path.read_bytes() == before and provider_credentials.load('openai_codex') == {}
    assert calls == ['https://auth.openai.com/api/accounts/deviceauth/usercode']
    message = capsys.readouterr().out
    assert 'HTTP 530' in message and '1016' in message and 'device-code request' in message
    assert 'STEP 2/2' not in message and 'private-token' not in message


@pytest.fixture(autouse=True)
def isolated_model_catalog(monkeypatch):
    monkeypatch.setattr(llm_codex, "list_models", lambda: [{"id": "account-model", "name": "Account model"}])
