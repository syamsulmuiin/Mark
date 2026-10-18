import io
import json
from urllib.error import HTTPError

import pytest
from core import llm_codex, setup_config


def test_account_catalog_auth_filtering_and_bounds(monkeypatch):
    monkeypatch.setattr(llm_codex, 'check_login', lambda: {'access_token': 'secret', 'account_id': 'acct'})
    def request(req, **kwargs):
        assert req.full_url == 'https://chatgpt.com/backend-api/codex/models?client_version=1.0.0'
        assert req.get_method() == 'GET' and req.data is None
        assert req.get_header('Authorization') == 'Bearer secret'
        assert req.get_header('Chatgpt-account-id') == 'acct'
        return io.BytesIO(json.dumps({'models': [
            {'slug': 'account-model', 'display_name': 'Account\nModel', 'visibility': 'list', 'supported_in_api': False},
            {'slug': 'account-model', 'visibility': 'list'},
            {'slug': 'hidden', 'visibility': 'hide'},
            {'slug': 'audio', 'visibility': 'list', 'input_modalities': ['audio']},
            {'slug': 'bad\x1b', 'visibility': 'list'}, None]}).encode())
    monkeypatch.setattr(llm_codex, 'urlopen', request)
    assert llm_codex.list_models() == [{'id': 'account-model', 'name': 'AccountModel'}]


@pytest.mark.parametrize('raw', [b'private invalid body', b'[]', b'{"models": {}}', b'x' * (2 * 1024 * 1024 + 1)])
def test_bad_catalog_is_sanitized(monkeypatch, raw):
    monkeypatch.setattr(llm_codex, 'check_login', lambda: {'access_token': 'secret', 'account_id': 'acct'})
    monkeypatch.setattr(llm_codex, 'urlopen', lambda *a, **k: io.BytesIO(raw))
    with pytest.raises(RuntimeError) as exc:
        llm_codex.list_models()
    assert 'private' not in str(exc.value) and 'secret' not in str(exc.value)


def test_401_invalidates_account_without_fallback(monkeypatch):
    monkeypatch.setattr(llm_codex, 'check_login', lambda: {'access_token': 'secret', 'account_id': 'acct'})
    invalidated = []
    monkeypatch.setattr(llm_codex.credentials, 'invalidate', invalidated.append)
    def fail(*args, **kwargs):
        raise HTTPError('https://chatgpt.com', 401, 'private', {}, None)
    monkeypatch.setattr(llm_codex, 'urlopen', fail)
    with pytest.raises(RuntimeError, match='HTTP 401'):
        llm_codex.list_models()
    assert invalidated == ['openai_codex']


@pytest.mark.parametrize('answer,saved,expected', [('2', '', 'second'), ('', 'saved', 'saved'), ('', '', ''), ('custom-model', '', 'custom-model')])
def test_numbered_or_explicit_choice(monkeypatch, answer, saved, expected):
    monkeypatch.setattr(llm_codex, 'list_models', lambda: [{'id': 'first', 'name': 'First'}, {'id': 'second', 'name': 'Second'}])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: answer)
    assert setup_config._choose_codex_model(saved) == expected


def test_catalog_failure_permits_manual_choice(monkeypatch, capsys):
    def fail():
        raise RuntimeError('OpenAI account model catalog HTTP 530')
    monkeypatch.setattr(llm_codex, 'list_models', fail)
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: 'explicit-model')
    assert setup_config._choose_codex_model('') == 'explicit-model'
    assert 'HTTP 530' in capsys.readouterr().out


@pytest.mark.parametrize('answer', ['0', '3', 'bad model', '\x1b'])
def test_invalid_choice_is_not_saved_as_id(monkeypatch, answer):
    monkeypatch.setattr(llm_codex, 'list_models', lambda: [{'id': 'first', 'name': 'First'}])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: answer)
    with pytest.raises(ValueError):
        setup_config._choose_codex_model('')
