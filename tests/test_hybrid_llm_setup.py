"""Gemini hybrid setup must preserve credentials and reject unsupported providers."""
import json
import pytest
from core import setup_config


def test_gemini_hybrid_selection_preserves_api_key(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text(json.dumps({"gemini_api_key": "secret", "os_system": "Linux"}))
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    saved = setup_config.save_llm_selection(
        "gemini", "hybrid", "gemini-live-a,gemini-live-b",
        "gemini-text-a,gemini-text-b"
    )
    assert saved["gemini_api_key"] == "secret"
    assert saved["llm_provider"] == "gemini"
    assert saved["llm_mode"] == "hybrid"
    assert saved["live_models"] == "gemini-live-a,gemini-live-b"
    assert saved["text_models"] == "gemini-text-a,gemini-text-b"
    assert path.stat().st_mode & 0o077 == 0


def test_unimplemented_providers_and_modes_are_rejected(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text('{"gemini_api_key":"secret"}')
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    before = path.read_text()
    for provider, mode in (("gemini", "text"), ("ollama", "hybrid")):
        with pytest.raises(ValueError):
            setup_config.save_llm_selection(provider, mode)
    assert path.read_text() == before


def test_interactive_selection_defaults_to_gemini_hybrid(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text('{"gemini_api_key":"secret"}')
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    answers = iter(["", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert setup_config.interactive_llm_setup()
    saved = json.loads(path.read_text())
    assert saved["llm_provider"] == "gemini"
    assert saved["llm_mode"] == "hybrid"
    assert saved["live_models"] and saved["text_models"]


def test_unsupported_chat_provider_does_not_change_saved_settings(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text('{"gemini_api_key":"secret","llm_provider":"gemini"}')
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    answers = iter(["2", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    before = path.read_text()
    assert not setup_config.interactive_llm_setup()
    assert path.read_text() == before


def test_unsupported_live_provider_does_not_change_saved_settings(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text('{"gemini_api_key":"secret","llm_provider":"gemini"}')
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    answers = iter(["1", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    before = path.read_text()
    assert not setup_config.interactive_llm_setup()
    assert path.read_text() == before

def test_text_provider_setup_saves_model_and_key(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text('{"gemini_api_key":"live-secret","os_system":"Linux"}')
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    answers = iter(["4", "1", "deepseek-chat", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(setup_config.getpass, "getpass", lambda _: "text-secret")
    assert setup_config.interactive_llm_setup()
    saved = json.loads(path.read_text())
    assert saved["llm_provider"] == "deepseek"
    assert saved["llm_mode"] == "hybrid"
    assert saved["deepseek_api_key"] == "text-secret"
    assert saved["gemini_api_key"] == "live-secret"
    assert saved["text_models"] == "deepseek-chat"


def test_text_provider_without_model_does_not_change_config(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text('{"gemini_api_key":"live-secret","os_system":"Linux"}')
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    answers = iter(["4", "1", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(setup_config.getpass, "getpass", lambda _: "text-secret")
    before = path.read_text()
    assert not setup_config.interactive_llm_setup()
    assert path.read_text() == before
