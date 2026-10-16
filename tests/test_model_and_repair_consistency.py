from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def test_server_model_roles_are_configurable():
    from core import model_config
    assert model_config.get_live_models() == (
        model_config.DEFAULT_LIVE_MODEL,
        model_config.DEFAULT_LIVE_FALLBACK_MODEL,
    )
    assert model_config.get_text_models() == model_config.DEFAULT_TEXT_MODELS
    assert model_config.get_chat_models() == model_config.get_text_models()


def test_no_unavailable_rolling_aliases_in_defaults():
    from core import model_config
    for model in (*model_config.get_live_models(), *model_config.get_text_models()):
        assert "gemini-flash-latest" not in model


def test_desktop_compat_model_defaults_are_present():
    src = (ROOT / "desktop-companion/runtime/core/model_config.py").read_text(encoding="utf-8")
    assert "DEFAULT_LIVE_MODEL" in src
    assert "DEFAULT_TEXT_MODEL" in src


def test_repair_apply_supports_server_side_plan_id():
    src=(ROOT/"actions/self_repair_apply.py").read_text(encoding="utf-8")
    assert '"plan_id"' in src
    assert "_load_plan(plan_id)" in src
    assert 'params[key] = plan[key]' in src

def test_diagnostic_plan_requires_exact_source_match():
    src=(ROOT/"actions/self_repair_diagnostic.py").read_text(encoding="utf-8")
    assert "current.count(old) != 1" in src
    assert "_save_plan" in src

def test_live_orchestration_continues_authorized_repair():
    src=(ROOT/"main.py").read_text(encoding="utf-8")
    assert "self._last_repair_plan_id" in src
    assert "Do not stop at the read-only diagnosis" in src
    assert "has_explicit_repair_apply_intent(_last_user)" in src
