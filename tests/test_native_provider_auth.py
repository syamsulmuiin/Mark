import base64
import json
import subprocess
import time
import pytest
from core import llm_codex as codex, provider_credentials as store, provider_oauth as oauth


class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return self.data
    def __iter__(self): return iter(self.data.splitlines(keepends=True))


@pytest.fixture
def auth(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'auth')
    record = {'access_token': 'secret-access', 'refresh_token': 'secret-refresh',
              'account_id': 'account', 'expires_at': time.time() + 3600}
    store.save('openai_codex', record)
    return record


def token_response():
    claim = base64.urlsafe_b64encode(json.dumps({'https://api.openai.com/auth': {'chatgpt_account_id': 'account'}}).encode()).decode().rstrip('=')
    return {'access_token': 'new-access', 'refresh_token': 'new-refresh', 'id_token': 'x.' + claim + '.x', 'expires_in': 3600}


def test_native_device_login_stores_private_mark_owned_tokens(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'auth')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('must not invoke CLI'))
    calls = []
    def post(url, data, **kwargs):
        calls.append((url, data))
        if url.endswith('/usercode'): return {'device_auth_id': 'device', 'user_code': 'ONE-TIME', 'interval': '1'}
        if url.endswith('/deviceauth/token'): return {'authorization_code': 'code', 'code_verifier': 'verifier'}
        return token_response()
    monkeypatch.setattr(codex, 'post', post)
    codex.login()
    saved = store.load('openai_codex')
    assert saved['account_id'] == 'account' and saved['access_token'] == 'new-access'
    assert calls[-1][1]['code_verifier'] == 'verifier'
    assert store._path('openai_codex').stat().st_mode & 0o077 == 0
    output = capsys.readouterr().out
    assert 'ONE-TIME' in output and 'new-access' not in output and 'new-refresh' not in output


def test_refresh_replaces_token_and_terminal_failure_is_not_replayed(auth, monkeypatch):
    auth['expires_at'] = 0
    store.save('openai_codex', auth)
    calls = []
    monkeypatch.setattr(codex, 'post', lambda *a, **kw: calls.append(a) or token_response())
    assert codex.check_login()['access_token'] == 'new-access'
    assert len(calls) == 1
    codex.check_login()
    assert len(calls) == 1
    store.save('openai_codex', auth)
    def revoked(*a, **kw):
        calls.append(a)
        raise oauth.AuthHTTPError(400)
    monkeypatch.setattr(codex, 'post', revoked)
    with pytest.raises(RuntimeError, match='revoked'): codex.check_login()
    count = len(calls)
    with pytest.raises(RuntimeError, match='login required'): codex.check_login()
    assert len(calls) == count


def test_native_text_stream_uses_exact_model_and_no_cli_or_tools(auth, monkeypatch):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('no CLI'))
    captured = []
    def request(req, **kwargs):
        captured.append(req)
        return Response(b'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"Answer"}]}]}}\n\n')
    monkeypatch.setattr(codex, 'urlopen', request)
    assert codex.generate_text('exact-model', 'user prompt') == 'Answer'
    payload = json.loads(captured[0].data)
    assert payload['model'] == 'exact-model' and payload['tools'] == [] and payload['store'] is False
    assert captured[0].full_url == codex.ENDPOINT
    assert captured[0].get_header('Authorization') == 'Bearer secret-access'


@pytest.mark.parametrize('data', [b'data: {"type":"response.output_text.delta","delta":"partial"}\n',
    b'data: {"type":"response.failed"}\n', b'data: {"type":"response.incomplete"}\n', b'data: invalid-json\n'])
def test_incomplete_or_invalid_stream_is_not_a_success(auth, monkeypatch, data):
    monkeypatch.setattr(codex, 'urlopen', lambda *a, **kw: Response(data))
    with pytest.raises(RuntimeError): codex.generate_text('model', 'prompt')


def test_headless_openrouter_pkce_code_exchange_does_not_expose_key(monkeypatch):
    calls, messages = [], []
    def post(url, data, **kw):
        calls.append((url, data))
        return {'key': 'private-key'}
    monkeypatch.setattr(oauth, 'post', post)
    key = oauth.openrouter_login(lambda _: 'one-time-code', messages.append)
    assert key == 'private-key'
    assert 'callback_url' not in messages[-1] and 'code_challenge_method=S256' in messages[-1]
    assert calls[0][1]['code_verifier'] not in messages[-1]
    assert 'private-key' not in str(messages)


@pytest.mark.parametrize('url', ['http://localhost:8765/mark/google?code=x&state=bad',
    'https://evil.example/callback?code=x&state=ok',
    'http://localhost:8765/mark/google?code=x&code=y&state=ok'])
def test_google_callback_is_bound_to_exact_login(url):
    with pytest.raises(ValueError): oauth.callback_code(url, 'http://localhost:8765/mark/google', 'ok')


def test_oauth_http_transport_never_follows_arbitrary_endpoint():
    with pytest.raises(ValueError, match='Untrusted'): oauth.post('https://evil.example/token', {'refresh_token': 'private'})


def test_google_oauth_rest_uses_own_project_and_no_api_key(tmp_path, monkeypatch):
    from core import llm_google_oauth as google
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'auth')
    store.save('google_oauth', {'project': 'my-project', 'credentials': {
        'token': 'google-access', 'refresh_token': 'refresh', 'client_id': 'own-client',
        'client_secret': 'own-secret', 'token_uri': 'https://oauth2.googleapis.com/token',
        'expiry': '2099-01-01T00:00:00Z'}})
    captured = []
    def request(req, **kwargs):
        captured.append(req)
        return Response(b'{"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"Google answer"}]}}]}')
    monkeypatch.setattr(google, 'urlopen', request)
    assert google.generate_text('gemini-selected', 'prompt') == 'Google answer'
    assert captured[0].get_header('Authorization') == 'Bearer google-access'
    assert captured[0].get_header('X-goog-user-project') == 'my-project'
    assert captured[0].get_header('X-goog-api-key') is None


def test_google_login_uses_own_client_pkce_and_state(tmp_path, monkeypatch):
    from core import llm_google_oauth as google
    from google_auth_oauthlib.flow import InstalledAppFlow
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'auth')
    client = tmp_path / 'client.json'
    client.write_text(json.dumps({'installed': {'client_id': 'own-client', 'client_secret': 'own-secret',
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token'}}))
    captured = []
    class Cred:
        refresh_token = 'private-refresh'
        def with_quota_project(self, project): return self
        def to_json(self): return '{"refresh_token":"private-refresh"}'
    class Flow:
        credentials = Cred()
        def authorization_url(self, **kw): return 'https://accounts.google.com/authorize', 'state'
        def fetch_token(self, **kw): captured.append(kw)
    def flow(config, scopes, **kwargs):
        assert config['installed']['client_id'] == 'own-client'
        assert kwargs['autogenerate_code_verifier'] is True
        return Flow()
    monkeypatch.setattr(InstalledAppFlow, 'from_client_config', flow)
    answers = iter([str(client), 'my-project'])
    messages = []
    google.login(lambda _: next(answers), lambda _: google.REDIRECT + '?code=one-time&state=state', messages.append)
    assert captured == [{'code': 'one-time'}]
    assert store.load('google_oauth')['project'] == 'my-project'
    assert 'private-refresh' not in str(messages)


def test_google_rejects_oauth_client_with_foreign_token_endpoint(tmp_path):
    from core import llm_google_oauth as google
    client = tmp_path / 'client.json'
    client.write_text(json.dumps({'installed': {'auth_uri': 'https://evil.example/auth',
        'token_uri': 'https://evil.example/token'}}))
    with pytest.raises(RuntimeError, match='official Google'):
        google.login(lambda _: str(client), lambda _: 'unused')


def test_google_router_does_not_fall_back_to_api_key_provider(monkeypatch):
    from core import chat_router, llm_google_oauth
    calls = []
    monkeypatch.setattr(llm_google_oauth, 'generate_text', lambda *a, **kw: calls.append((a, kw)) or 'answer')
    monkeypatch.setattr(chat_router, 'generate_text', lambda *a, **kw: pytest.fail('no fallback'))
    assert chat_router.generate_chat_text('prompt', config={'llm_provider': 'google_oauth', 'chat_models': 'exact-model'}) == 'answer'
    assert calls == [(('exact-model', 'prompt'), {'timeout': 30.0})]


def test_device_login_pending_is_bounded_and_saves_no_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'auth')
    clock = [0.0]
    monkeypatch.setattr(codex.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(codex.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    calls = []
    def post(url, data, **kwargs):
        calls.append(url)
        if url.endswith('/usercode'): return {'device_auth_id': 'device', 'user_code': 'code', 'interval': '1'}
        raise oauth.AuthHTTPError(403)
    monkeypatch.setattr(codex, 'post', post)
    with pytest.raises(RuntimeError, match='expired'): codex.login(lambda *a: None, timeout=2)
    assert len(calls) == 3 and store.load('openai_codex') == {}


def test_auth_http_error_never_echoes_provider_response_secrets(monkeypatch):
    from urllib.error import HTTPError
    def rejected(*a, **kwargs):
        raise HTTPError('https://auth.openai.com/oauth/token', 401, 'private-token', {}, None)
    monkeypatch.setattr(oauth, 'urlopen', rejected)
    with pytest.raises(oauth.AuthHTTPError) as error:
        oauth.post('https://auth.openai.com/oauth/token', {'refresh_token': 'private-token'})
    assert '401' in str(error.value) and 'private-token' not in str(error.value)
