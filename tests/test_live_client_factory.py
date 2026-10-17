"""Regression tests for the provider-independent Live client entry point."""
import pytest
from core import llm_live


def test_client_rejects_unimplemented_provider():
    with pytest.raises(NotImplementedError):
        llm_live.client({"live_provider": "openai_realtime"})


def test_client_selects_gemini_api_version(monkeypatch):
    from google import genai
    from core import gemini
    calls = []
    monkeypatch.setattr(gemini, "api_key", lambda: "test-key")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: calls.append(kwargs) or object())
    llm_live.client({}, enhanced=False)
    llm_live.client({}, enhanced=True)
    assert calls == [
        {"api_key": "test-key", "http_options": {"api_version": "v1beta"}},
        {"api_key": "test-key", "http_options": {"api_version": "v1alpha"}},
    ]
