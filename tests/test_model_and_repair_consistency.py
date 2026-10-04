from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def test_server_default_model_roles_are_exactly_four():
    from core import model_config
    assert model_config.get_live_models() == (
        "models/gemini-3.8-live",
        "models/gemini-3.1-flash-live-preview",
    )
    assert model_config.get_text_models() == (
        "gemini-3.7-flash",
        "gemini-3.5-flash-lite",
    )

def test_no_legacy_default_model_ladder():
    src=(ROOT/"core/model_config.py").read_text(encoding="utf-8")
    block=src[src.index("DEFAULT_TEXT_MODELS"):src.index("DEFAULT_QUOTA")]
    for legacy in ("gemini-2.5", "gemini-flash-latest", "gemini-flash-lite-latest"):
        assert legacy not in block

def test_desktop_compat_model_defaults_match_server():
    src=(ROOT/"desktop-companion/runtime/core/model_config.py").read_text(encoding="utf-8")
    for model in ("models/gemini-3.8-live","models/gemini-3.1-flash-live-preview","gemini-3.7-flash","gemini-3.5-flash-lite"):
        assert model in src
    helper=(ROOT/"desktop-companion/runtime/core/gemini.py").read_text(encoding="utf-8")
    assert "gemini-2.5-flash" not in helper
    assert "gemini-flash-latest" not in helper

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
