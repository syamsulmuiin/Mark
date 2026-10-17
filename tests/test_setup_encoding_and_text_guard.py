"""Regression checks for setup, Claude routing and Live action guard."""
from pathlib import Path
import io
import json
import sys
from core import setup_config, chat_router


def test_safe_input_replaces_invalid_utf8(monkeypatch):
    fake = io.TextIOWrapper(io.BytesIO(bytes([53, 255, 10])), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", fake)
    assert setup_config._safe_input("Provider: ").startswith("5")


def test_claude_routing(monkeypatch):
    from core import llm_anthropic
    monkeypatch.setattr(llm_anthropic, "generate_text", lambda model, prompt, api_key: model + ":" + prompt)
    result = chat_router.generate_chat_text("hello", config={
        "llm_provider": "anthropic", "chat_models": "claude-test", "anthropic_api_key": "secret"
    })
    assert result == "claude-test:hello"


def test_non_gemini_direct_actions_are_blocked_in_source():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'if _text_provider != "gemini":' in source
    assert 'Direct Live action blocked:' in source
    assert 'self._approved_text_action_context.set(True)' in source
    assert 'self._approved_text_action_context.reset(approval_context)' in source
