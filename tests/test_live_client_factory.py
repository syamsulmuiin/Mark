"""Regression tests for the provider-independent Live client entry point."""
import sys
import types
import pytest
from core import llm_live


def test_client_rejects_unimplemented_provider():
    with pytest.raises(NotImplementedError):
        llm_live.client({"live_provider": "openai_realtime"})


def test_client_selects_gemini_api_version(monkeypatch):
    calls = []
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = lambda **kwargs: calls.append(kwargs) or object()
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    fake_gemini = types.ModuleType("core.gemini")
    fake_gemini.api_key = lambda: "test-key"
    monkeypatch.setitem(sys.modules, "core.gemini", fake_gemini)
    llm_live.client({}, enhanced=False)
    llm_live.client({}, enhanced=True)
    assert calls == [
        {"api_key": "test-key", "http_options": {"api_version": "v1beta"}},
        {"api_key": "test-key", "http_options": {"api_version": "v1alpha"}},
    ]
