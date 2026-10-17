"""Contract checks for the two stable LLM entry points."""
import pytest
from core import llm_live, llm_text


def test_text_delegates_to_router(monkeypatch):
    monkeypatch.setattr(llm_text, "generate_chat_text", lambda prompt, config=None: "routed:" + prompt)
    assert llm_text.generate("hello") == "routed:hello"


def test_live_rejects_unimplemented_provider():
    with pytest.raises(NotImplementedError):
        llm_live.provider({"live_provider": "unknown"})


def test_live_defaults_to_gemini():
    assert llm_live.provider({}) == "gemini"
