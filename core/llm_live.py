"""Single entry point for live provider selection.

Select Gemini Live or OpenAI Realtime explicitly. Both clients expose the
session interface consumed by main.py; failures never change providers.
"""
from __future__ import annotations
from core.setup_config import load_config


def provider(config: dict | None = None) -> str:
    settings = load_config() if config is None else config
    from core.model_profiles import enabled, primary
    if enabled(settings):return primary('live',settings)['provider']
    selected = str(settings.get("live_provider") or "gemini").strip().lower()
    if selected not in {"gemini", "openai_realtime"}:
        raise NotImplementedError(f"Live provider {selected!r} is not implemented")
    return selected


def model(config: dict | None = None) -> str:
    settings=load_config() if config is None else config
    from core.model_profiles import enabled, primary
    if enabled(settings):return primary('live',settings)['model']
    if provider(config) == "openai_realtime":
        settings = load_config() if config is None else config
        return str(settings.get("realtime_model") or "gpt-realtime-2.1").strip()
    from core.gemini import live_model
    return live_model()


def client(config: dict | None = None, *, enhanced: bool = False):
    """Create a fresh selected-provider client for each connection attempt.

    Preserve the existing v1alpha/v1beta selection for proactive audio.
    """
    settings=load_config() if config is None else config
    from core.model_profiles import enabled, primary
    if enabled(settings):
        p=primary('live',settings)
        if p['provider']=='openai_realtime':
            from core.llm_openai_realtime import RealtimeClient
            return RealtimeClient({**settings,'openai_api_key':p.get('api_key',''),'realtime_model':p['model']})
        from google import genai
        return genai.Client(api_key=p.get('api_key',''),http_options={'api_version':'v1alpha' if enhanced else 'v1beta'})
    if provider(config) == "openai_realtime":
        from core.llm_openai_realtime import RealtimeClient
        return RealtimeClient(load_config() if config is None else config)
    from google import genai
    from core.gemini import api_key
    return genai.Client(
        api_key=api_key(),
        http_options={"api_version": "v1alpha" if enhanced else "v1beta"},
    )


def note_model_failure(model_name: str, error: str, config: dict | None = None) -> bool:
    """Register a Gemini Live model failure without exposing its adapter to callers."""
    if provider(config) == "openai_realtime":
        return False  # never switch to Gemini or a different provider on failure
    from core.gemini import note_live_failure
    note_live_failure(model_name, error)
    return False  # failure is recorded, but no alternative model/provider is authorized
