"""Explicit image input for the configured Text model; never route to Live or fallback."""
from __future__ import annotations

import base64
from core.setup_config import load_config
from core.llm_trace import traced_text_call


class VisualReviewUnavailable(RuntimeError):
    pass


def visual_provider(config=None):
    settings = load_config() if config is None else config
    from core.model_profiles import enabled, primary
    if enabled(settings):
        from core.model_profiles import RouteUnavailable
        try:p=primary('vision',settings)
        except RouteUnavailable as exc:raise VisualReviewUnavailable(str(exc)) from None
        return settings,p['provider']
    provider = str(settings.get('llm_provider') or 'gemini').strip().lower()
    if provider not in {'gemini','openai','openai_codex','anthropic','google_oauth',
                         'openrouter','ollama_local','ollama_cloud'}:
        raise VisualReviewUnavailable('Configured Text provider has no image-input adapter; no fallback')
    return settings, provider


def generate_visual(prompt, images, *, timeout=30, config=None):
    """Images are bounded JPEG base64 previews, never remote URLs or arbitrary files."""
    settings, provider = visual_provider(config)
    if not 1 <= len(images) <= 6 or any(not isinstance(i,str) or len(i)>2_000_000 for i in images):
        raise ValueError('Invalid image review batch')
    from core.model_profiles import enabled, run
    if enabled(settings):
        from core.profile_execution import infer
        return run('vision',lambda p,remaining:infer(p,prompt,images=images,timeout=remaining),settings=settings,timeout=timeout)
    if provider == 'gemini':
        from core.gemini import text, SMART, _LADDERS
        from google.genai import types
        model = _LADDERS[SMART][0]
        parts = [types.Part.from_text(text=prompt)] + [
            types.Part.from_bytes(data=base64.b64decode(i,validate=True),mime_type='image/jpeg') for i in images]
        return traced_text_call(provider,model,lambda:text(parts,tier=SMART,timeout_ms=int(timeout*1000)))
    models = str((settings.get('provider_models') or {}).get(provider)
                 or settings.get('chat_models') or settings.get('text_models') or '')
    model = next((m.strip() for m in models.split(',') if m.strip()), '')
    if not model:
        raise VisualReviewUnavailable('Configure the primary Text model')
    if provider == 'openai_codex':
        from core.llm_codex import generate_text
        call = lambda:generate_text(model,prompt,timeout=timeout,images=images)
    elif provider == 'google_oauth':
        from core.llm_google_oauth import generate_text
        call = lambda:generate_text(model,prompt,timeout=timeout,images=images)
    elif provider == 'anthropic':
        from core.llm_anthropic import generate_text
        call = lambda:generate_text(model,prompt,api_key=str(settings.get('anthropic_api_key') or ''),timeout=timeout,images=images)
    else:
        from core.llm_compatible import generate_text
        call = lambda:generate_text(provider,model,prompt,api_key=str(settings.get(provider+'_api_key') or ''),timeout=timeout,images=images)
    return traced_text_call(provider,model,call)
