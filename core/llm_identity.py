"""Credential-free model identity supplied to conversation models by the host."""
from __future__ import annotations
import json
import os
from core.setup_config import load_config


def identity_instruction(config=None, *, text_model=None, live_model=None, role='Live'):
    settings = load_config() if config is None else config
    from core.model_config import get_live_models, get_text_models
    provider = str(settings.get('llm_provider') or 'gemini').strip().lower()
    voice = str(settings.get('live_provider') or 'gemini').strip().lower()
    if text_model is None:
        text_model = (get_text_models()[0] if provider == 'gemini' else
                      str((settings.get('provider_models') or {}).get(provider)
                          or settings.get('chat_models') or settings.get('text_models') or '').split(',')[0].strip())
    if live_model is None:
        live_model = (str(settings.get('realtime_model') or 'gpt-realtime-2.1').strip()
                      if voice == 'openai_realtime' else str(os.getenv('ASSISTANT_LIVE_MODELS', '').strip()
                               or settings.get('live_models')
                               or os.getenv('ASSISTANT_LIVE_MODEL', '').strip()
                               or settings.get('live_model') or get_live_models()[0]).split(',')[0].strip())
    names = {'openai_codex': 'OpenAI / Codex account', 'gemini': 'Google Gemini',
             'openai_realtime': 'OpenAI Realtime', 'anthropic': 'Anthropic Claude API'}
    snapshot = {'responding_role': role,
                'text': {'provider': names.get(provider, provider), 'model': text_model or 'not configured'},
                'live': {'provider': 'Gemini Live' if voice == 'gemini' else names.get(voice, voice), 'model': live_model},
                'automatic_fallback': False}
    return ('[HOST MODEL IDENTITY]\n' + json.dumps(snapshot, ensure_ascii=True) + '\n'
            'When asked which AI, provider or model Mark/Jarvis uses, report BOTH Text and Live roles from this host metadata. '
            'Do not substitute your training identity, infer a provider from the assistant name, or invent a model ID. '
            'These are selected routes; they do not prove that a particular previous request succeeded. '
            'Use runtime diagnostics and request traces for past-call or connection verification. '
            'Never claim an automatic provider/model fallback.\n')
