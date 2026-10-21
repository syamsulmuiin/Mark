"""The public setup flow must configure the active model policy without installs."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from core import model_profiles, setup_config


def settings():
    return {
        "os_system": "Linux",
        "gemini_api_key": "voice-secret",
        "llm_provider": "deepseek",
        "deepseek_api_key": "text-secret",
        "provider_models": {"deepseek": "text-test"},
        "live_models": "voice-test",
    }


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text(json.dumps(settings()))
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    return path


def answer(monkeypatch, values):
    replies = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))


def load_installer():
    spec = importlib.util.spec_from_file_location(
        "mark_installer_test", Path(__file__).resolve().parents[1] / "setup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configuration_only_skips_dependency_and_browser_install(monkeypatch):
    installer = load_installer()
    monkeypatch.setattr(installer, "_check_python", lambda: None)
    monkeypatch.setattr(installer, "_ensure_linux_venv", lambda: None)
    monkeypatch.setattr(
        installer, "_run", lambda *a: pytest.fail("Must not install dependencies")
    )
    monkeypatch.setattr(
        installer,
        "_ensure_browser_runtime",
        lambda: pytest.fail("Must not install Chromium"),
    )
    opened = []
    monkeypatch.setattr(
        setup_config, "interactive_model_setup", lambda: opened.append(True) or True
    )
    installer.main(["--configure-models"])
    assert opened == [True]


def test_regular_setup_opens_same_model_menu(monkeypatch):
    installer = load_installer()
    for name in ("_check_python", "_ensure_linux_venv", "_ensure_browser_runtime"):
        monkeypatch.setattr(installer, name, lambda: None)
    monkeypatch.setattr(installer, "_run", lambda *a: None)
    monkeypatch.setattr(installer.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(setup_config, "configured", lambda: True)
    monkeypatch.setattr(setup_config, "_safe_input", lambda prompt: "y")
    monkeypatch.setattr(setup_config, "interactive_language_setup", lambda: True)
    opened = []
    monkeypatch.setattr(
        setup_config, "interactive_model_setup", lambda: opened.append(True) or True
    )
    installer.main([])
    assert opened == [True]


def test_active_profiles_do_not_open_ignored_legacy_wizard(config_file, monkeypatch):
    cfg = settings()
    cfg["model_routing"] = model_profiles.from_legacy(cfg)
    config_file.write_text(json.dumps(cfg))
    opened = []
    monkeypatch.setattr(
        setup_config, "interactive_model_setup", lambda: opened.append(True) or True
    )
    assert setup_config.interactive_llm_setup()
    assert opened == [True]


def test_menu_summarizes_tasks_without_secrets_or_internal_ids(
    config_file, monkeypatch, capsys
):
    before = config_file.read_bytes()
    answer(monkeypatch, ["4"])
    assert model_profiles.configure() is False
    output = capsys.readouterr().out
    assert "Text / reasoning: DeepSeek / text-test" in output
    assert "Live / voice: Google Gemini / voice-test" in output
    assert "Image generation: Not configured" in output
    assert "\n  1. Add a model\n  2. Choose models for tasks" in output
    for hidden in (
        "text-secret",
        "voice-secret",
        "current_text",
        "current_live",
        "not certified",
    ):
        assert hidden not in output
    assert config_file.read_bytes() == before


def test_numbered_provider_capability_and_route_selection(config_file, monkeypatch):
    monkeypatch.setattr(
        model_profiles, "discover_models", lambda *a: ["gpt-image-test"]
    )
    monkeypatch.setattr(
        model_profiles.getpass, "getpass", lambda prompt: "image-secret"
    )
    # Add OpenAI image generation, then select existing Text/Live and the new image route.
    answer(
        monkeypatch, ["1", "2", "3", "1", "Illustrations", "", "2", "", "", "1", "3"]
    )
    assert model_profiles.configure()
    cfg = json.loads(config_file.read_text())
    policy = cfg["model_routing"]
    assert model_profiles.primary("image", cfg)["model"] == "gpt-image-test"
    assert model_profiles.primary("image", cfg)["api_key"] == "image-secret"
    assert policy["routes"]["text"] == ["current_text"]
    assert policy["routes"]["live"] == ["current_live"]
    assert not policy["failover"]
    assert cfg["deepseek_api_key"] == "text-secret"


def test_invalid_menu_choice_recovers_without_saving(config_file, monkeypatch, capsys):
    before = config_file.read_bytes()
    answer(monkeypatch, ["not-a-choice", "4"])
    assert model_profiles.configure() is False
    assert "Choose an option from 1 to 6" in capsys.readouterr().out
    assert config_file.read_bytes() == before


def test_invalid_add_does_not_mutate_draft(config_file, monkeypatch):
    answer(monkeypatch, ["1", "999", "3"])
    assert model_profiles.configure()
    assert len(json.loads(config_file.read_text())["model_routing"]["profiles"]) == 2


def test_required_roles_cannot_be_disabled_by_mistake(config_file, monkeypatch, capsys):
    before = config_file.read_bytes()
    answer(monkeypatch, ["2", "0", "", "3", "4"])
    assert model_profiles.configure() is False
    assert "Choose a Text and a Live model before saving" in capsys.readouterr().out
    assert config_file.read_bytes() == before


def test_linux_venv_relaunch_preserves_configuration_flag(tmp_path, monkeypatch):
    installer = load_installer()
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(installer, "OS", "Linux")
    monkeypatch.setattr(installer, "_in_venv", lambda: False)
    monkeypatch.setattr(installer, "_venv_python", lambda: python)
    monkeypatch.delenv("ASSISTANT_SETUP_IN_VENV", raising=False)
    monkeypatch.setattr(installer.sys, "argv", ["setup.py", "--configure-models"])
    calls = []
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0),
    )
    with pytest.raises(SystemExit) as stopped:
        installer._ensure_linux_venv()
    assert stopped.value.code == 0
    assert calls[0][-1] == "--configure-models"


def test_route_prompt_keeps_existing_priority_and_failover(config_file):
    policy = model_profiles.from_legacy(settings())
    policy["profiles"].append(
        {
            "id": "extra",
            "provider": "deepseek",
            "model": "second",
            "capabilities": ["text"],
            "api_key": "other",
        }
    )
    policy["routes"]["text"] = ["extra", "current_text"]
    policy["failover"] = ["text"]
    prompts = []

    def keep(prompt):
        prompts.append(prompt)
        return ""

    model_profiles._assign_tasks(policy, keep)
    assert any("[2,1]" in prompt for prompt in prompts)
    assert policy["routes"]["text"] == ["extra", "current_text"]
    assert policy["failover"] == ["text"]


def test_new_image_model_can_be_assigned_during_add(config_file, monkeypatch):
    monkeypatch.setattr(
        model_profiles, "discover_models", lambda *a: ["gpt-image-test"]
    )
    monkeypatch.setattr(
        model_profiles.getpass, "getpass", lambda prompt: "image-secret"
    )
    answer(monkeypatch, ["1", "2", "3", "1", "", "", "3"])
    assert model_profiles.configure()
    cfg = json.loads(config_file.read_text())
    assert model_profiles.primary("image", cfg)["model"] == "gpt-image-test"
    assert cfg["model_routing"]["failover"] == []
