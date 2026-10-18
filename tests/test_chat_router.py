"""Plain-text provider router never silently sends data to another provider."""
import pytest
from core import chat_router


def test_deepseek_route_uses_only_deepseek(monkeypatch):
    calls = []
    monkeypatch.setattr(chat_router, "generate_text",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or "OK")
    assert chat_router.generate_chat_text("hello", config={
        "llm_provider": "deepseek", "text_models": "deepseek-chat",
        "deepseek_api_key": "secret",
    }) == "OK"
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:2] == ("deepseek", "deepseek-chat") and kwargs == {"api_key": "secret"}
    assert args[2].startswith("[HOST MODEL IDENTITY]") and args[2].endswith("\n\nhello")


def test_unknown_provider_fails_closed():
    with pytest.raises(ValueError, match="not implemented"):
        chat_router.generate_chat_text("hello", config={"llm_provider": "unknown"})


def test_missing_model_fails_closed(monkeypatch):
    monkeypatch.setattr(chat_router, "generate_text",
                        lambda *a, **k: pytest.fail("must not call network"))
    with pytest.raises(ValueError, match="Configure a text model"):
        chat_router.generate_chat_text("hello", config={"llm_provider": "openai"})
