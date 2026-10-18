import json
from pathlib import Path
from types import SimpleNamespace as NS

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
    answers = iter(['3', 'account-model', '1', ''])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda _: pytest.fail('Codex account mode must not request API key'))
    monkeypatch.setattr(llm_codex, 'executable', lambda: '/bin/codex')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[1:] == ['login', 'status']:
            return NS(returncode=0, stdout='Logged in using ChatGPT', stderr='')
        Path(command[command.index('--output-last-message') + 1]).write_text('Codex answer')
        return NS(returncode=0)
    monkeypatch.setattr(llm_codex.subprocess, 'run', run)
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
    assert calls[-1][calls[-1].index('--model') + 1] == 'account-model'


def test_codex_failed_login_preserves_configuration(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'keys.json'
    path.write_text('{"gemini_api_key":"live-key","llm_provider":"deepseek"}')
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    answers = iter(['3', '1'])
    monkeypatch.setattr(setup_config, '_safe_input', lambda _: next(answers))
    monkeypatch.setattr(llm_codex, 'check_login', lambda: (_ for _ in ()).throw(RuntimeError('Codex is not signed in. Run codex login --device-auth')))
    before = path.read_bytes()
    assert not setup_config.interactive_llm_setup()
    assert path.read_bytes() == before
    output = capsys.readouterr().out
    assert 'codex login --device-auth' in output and 'not implemented' not in output


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
