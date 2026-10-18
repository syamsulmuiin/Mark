import base64
import json
import pytest
from core import llm_codex as codex, provider_credentials as store
from test_native_provider_auth import token_response

NOW = 1800000000


def jwt(claims):
    return 'x.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.x'


@pytest.mark.parametrize('lifetime', [30, 3600, 604800, 864000, '2592000'])
def test_provider_lifetime_has_no_arbitrary_one_minute_or_seven_day_limit(lifetime):
    assert codex._token_expiry({'expires_in': lifetime}, 'opaque-access-token', NOW) == NOW + float(lifetime)


@pytest.mark.parametrize('metadata', [{}, {'expires_in': None}, {'expires_in': ''}, {'expires_in': 'invalid'}, {'expires_in': float('nan')}])
def test_access_jwt_exp_handles_missing_or_unusable_relative_expiry(metadata):
    assert codex._token_expiry(metadata, jwt({'exp': NOW + 864000}), NOW) == NOW + 864000


def test_earliest_access_expiry_wins_and_id_token_is_not_used(monkeypatch):
    monkeypatch.setattr(codex.time, 'time', lambda: NOW)
    tokens = token_response()
    tokens['access_token'] = jwt({'exp': NOW + 120})
    tokens['id_token'] = jwt({'exp': NOW + 99999, 'https://api.openai.com/auth': {'chatgpt_account_id': 'account'}})
    assert codex._record(tokens)['expires_at'] == NOW + 120


@pytest.mark.parametrize('value', [None, 0, -1, 'private-not-a-number', float('inf'), float('nan'), True])
def test_missing_or_invalid_expiry_is_not_guessed_or_echoed(value):
    with pytest.raises(RuntimeError, match='no usable') as error:
        codex._token_expiry({'expires_in': value}, 'opaque', NOW)
    assert 'private-not-a-number' not in str(error.value)


def test_known_expired_access_token_is_rejected_even_with_relative_lifetime():
    with pytest.raises(RuntimeError, match='already expired'):
        codex._token_expiry({'expires_in': 864000}, jwt({'exp': NOW - 1}), NOW)


def test_device_login_and_refresh_both_accept_long_lived_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'auth')
    monkeypatch.setattr(codex.time, 'time', lambda: NOW)
    calls = []
    def post(url, data, **kwargs):
        calls.append(url)
        if url.endswith('/usercode'): return {'device_auth_id': 'device', 'user_code': 'code'}
        if url.endswith('/deviceauth/token'): return {'authorization_code': 'code', 'code_verifier': 'verifier'}
        tokens = token_response()
        tokens['expires_in'] = 864000
        return tokens
    monkeypatch.setattr(codex, 'post', post)
    codex.login(lambda *a: None)
    assert store.load('openai_codex')['expires_at'] == NOW + 864000
    assert codex.check_login()['expires_at'] == NOW + 864000
    assert len(calls) == 3
    record = store.load('openai_codex')
    record['expires_at'] = NOW
    store.save('openai_codex', record)
    assert codex.check_login()['expires_at'] == NOW + 864000
    assert len(calls) == 4


def test_setup_finishes_after_long_lived_device_login(tmp_path, monkeypatch):
    from core import setup_config
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'auth')
    config = tmp_path / 'keys.json'
    config.write_text('{"llm_provider":"deepseek","gemini_api_key":"voice-key"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', config)
    monkeypatch.setattr(codex.time, 'time', lambda: NOW)
    answers = iter(['3', '1', 'chosen-account-model', '1', ''])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda _: pytest.fail('account login does not require an API key'))
    def post(url, data, **kwargs):
        if url.endswith('/usercode'): return {'device_auth_id': 'device', 'user_code': 'code'}
        if url.endswith('/deviceauth/token'): return {'authorization_code': 'code', 'code_verifier': 'verifier'}
        tokens = token_response()
        tokens['expires_in'] = '864000'
        return tokens
    monkeypatch.setattr(codex, 'post', post)
    assert setup_config.interactive_llm_setup()
    saved = setup_config.load_config()
    assert saved['llm_provider'] == 'openai_codex' and saved['chat_models'] == 'chosen-account-model'
    assert saved['live_provider'] == 'gemini' and saved['gemini_api_key'] == 'voice-key'
    assert store.load('openai_codex')['expires_at'] == NOW + 864000
