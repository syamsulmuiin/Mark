"""Credential-free model identity supplied to conversation models by the host."""
from __future__ import annotations
import json
import os
from core.setup_config import load_config


def identity_instruction(config=None, *, text_model=None, live_model=None, role='Live'):
    explicit_text=text_model is not None
    explicit_live=live_model is not None
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
    from core.model_profiles import enabled, snapshot as profile_snapshot, primary, RouteUnavailable
    profile_state=profile_snapshot(settings) if enabled(settings) else None
    if profile_state:
        try:tp=primary('text',settings)
        except RouteUnavailable:tp={'provider':'not configured','model':'not configured'}
        try:lp=primary('live',settings)
        except RouteUnavailable:lp={'provider':'not configured','model':'not configured'}
        if not explicit_text:provider=tp['provider'];text_model=tp['model']
        voice=lp['provider']
        if not explicit_live:live_model=lp['model']
    names = {'openai_codex': 'OpenAI / Codex account', 'gemini': 'Google Gemini',
             'openai_realtime': 'OpenAI Realtime', 'anthropic': 'Anthropic Claude API'}
    snapshot = {'responding_role': role,
                'text': {'provider': names.get(provider, provider), 'model': text_model or 'not configured'},
                'live': {'provider': 'Gemini Live' if voice == 'gemini' else names.get(voice, voice), 'model': live_model},
                'automatic_fallback': bool(profile_state and profile_state['failover'])}
    if profile_state:snapshot['capability_routes']=profile_state
    return ('[HOST MODEL IDENTITY]\n' + json.dumps(snapshot, ensure_ascii=True) + '\n'
            'When asked which AI, provider or model Mark/Jarvis uses, report BOTH Text and Live roles from this host metadata. '
            'Do not substitute your training identity, infer a provider from the assistant name, or invent a model ID. '
            'These are selected routes; they do not prove that a particular previous request succeeded. '
            'Use runtime diagnostics and request traces for past-call or connection verification. '
            + ('Only configured capability routes and approved safe failover are permitted; Live failover is disabled.\n' if profile_state else 'Never claim an automatic provider/model fallback.\n'))
