import json
from core import llm_identity, llm_policy, chat_router


def snapshot(instruction):
    return json.loads(instruction.splitlines()[1])


def test_both_roles_and_exact_live_session_model_are_supplied_without_secrets():
    config = {'llm_provider': 'openai_codex', 'provider_models': {'openai_codex': 'chosen-account-model'},
              'gemini_api_key': 'never-disclose', 'live_provider': 'gemini'}
    policy = llm_policy.live_delegation_instruction(config, live_model='session-live-model')
    info = snapshot(policy)
    assert info['text'] == {'provider': 'OpenAI / Codex account', 'model': 'chosen-account-model'}
    assert info['live'] == {'provider': 'Gemini Live', 'model': 'session-live-model'}
    assert info['automatic_fallback'] is False
    assert 'never-disclose' not in policy
    assert 'do not prove' in policy and 'BOTH Text and Live' in policy


def test_text_adapter_receives_host_identity_and_uses_exact_model(monkeypatch):
    calls = []
    monkeypatch.setattr(chat_router, 'generate_codex_text', lambda model, prompt, **kw: calls.append((model, prompt)) or 'answer')
    config = {'llm_provider': 'openai_codex', 'provider_models': {'openai_codex': 'selected,unused'},
              'live_provider': 'openai_realtime', 'realtime_model': 'selected-realtime', 'openai_api_key': 'secret'}
    assert chat_router.generate_chat_text('Model apa?', config=config) == 'answer'
    model, prompt = calls[0]
    info = snapshot(prompt)
    assert model == 'selected' and info['text']['model'] == model
    assert info['responding_role'] == 'Text'
    assert info['live'] == {'provider': 'OpenAI Realtime', 'model': 'selected-realtime'}
    assert prompt.endswith('Model apa?') and 'secret' not in prompt


def test_gemini_trace_uses_actual_primary_model(monkeypatch):
    from core import gemini
    calls = []
    monkeypatch.setitem(gemini._LADDERS, gemini.SMART, ('primary', 'unused'))
    monkeypatch.setattr(gemini, 'text', lambda prompt, **kw: calls.append(prompt) or 'answer')
    traces = []
    monkeypatch.setattr(chat_router, 'traced_text_call', lambda provider, model, run: traces.append((provider, model)) or run())
    assert chat_router.generate_chat_text('question', config={'llm_provider': 'gemini'}) == 'answer'
    assert traces == [('gemini', 'primary')]
    assert snapshot(calls[0])['text']['model'] == 'primary'


def test_saved_live_choice_and_environment_override_are_reported(monkeypatch):
    monkeypatch.delenv('ASSISTANT_LIVE_MODEL', raising=False)
    monkeypatch.delenv('ASSISTANT_LIVE_MODELS', raising=False)
    config = {'llm_provider': 'openai_codex', 'chat_models': 'text', 'live_models': 'saved-live,unused'}
    assert snapshot(llm_identity.identity_instruction(config))['live']['model'] == 'saved-live'
    monkeypatch.setenv('ASSISTANT_LIVE_MODELS', 'environment-live,unused')
    assert snapshot(llm_identity.identity_instruction(config))['live']['model'] == 'environment-live'
