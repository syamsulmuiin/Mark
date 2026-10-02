import importlib

import pytest


@pytest.fixture()
def gemini():
    module = importlib.import_module("core.gemini")
    module._cooldown.clear()
    yield module
    module._cooldown.clear()


def test_cooldown_policy_uses_product_neutral_overrides(monkeypatch):
    from core import model_config

    monkeypatch.setenv("ASSISTANT_QUOTA_COOLDOWN_SECONDS", "7")
    monkeypatch.setenv("ASSISTANT_UNAVAILABLE_COOLDOWN_SECONDS", "11")
    monkeypatch.setenv("ASSISTANT_PERMISSION_COOLDOWN_SECONDS", "13")
    monkeypatch.setenv("ASSISTANT_GONE_COOLDOWN_SECONDS", "17")

    assert model_config.get_cooldown_policy() == {
        "quota": 7,
        "unavailable": 11,
        "permission": 13,
        "gone": 17,
    }


def test_error_categories_are_distinct(gemini):
    assert gemini.is_quota_error("429 RESOURCE_EXHAUSTED")
    assert gemini.is_unavailable_error("503 UNAVAILABLE")
    assert gemini.is_unavailable_error("504 DEADLINE_EXCEEDED")
    assert gemini.is_permission_error("403 PERMISSION_DENIED")
    assert gemini.is_gone_error("404 NOT_FOUND")
    assert not gemini.is_gone_error("403 PERMISSION_DENIED")
    assert not gemini.is_unavailable_error("network timeout")
    assert not gemini.is_gone_error("network timeout")


def test_note_failure_assigns_category_specific_cooldowns(gemini, monkeypatch):
    now = 1000.0
    monkeypatch.setattr(gemini.time, "monotonic", lambda: now)

    assert gemini.note_failure("quota-model", "429 RESOURCE_EXHAUSTED")
    assert gemini.note_failure("busy-model", "503 UNAVAILABLE")
    assert gemini.note_failure("permission-model", "403 PERMISSION_DENIED")
    assert gemini.note_failure("missing-model", "404 NOT_FOUND")
    assert not gemini.note_failure("network-model", "connection reset")

    assert gemini._cooldown["quota-model"] == pytest.approx(now + 300)
    assert gemini._cooldown["busy-model"] == pytest.approx(now + 60)
    assert gemini._cooldown["permission-model"] == pytest.approx(now + 1800)
    assert gemini._cooldown["missing-model"] == pytest.approx(now + 21600)
    assert "network-model" not in gemini._cooldown


def test_ladders_include_multiple_fallback_rungs(gemini):
    assert len(gemini._LADDERS[gemini.FAST]) >= 4
    assert len(gemini._LADDERS[gemini.SMART]) >= 4
    assert gemini.LIVE_MODELS[0]
    assert gemini.LIVE_MODELS[1]


def test_live_model_failover_skips_cooled_model(gemini):
    first, second = gemini.LIVE_MODELS[:2]
    gemini._cool(first, seconds=300)
    assert gemini.live_model() == second
    assert gemini.note_live_failure(second, "503 UNAVAILABLE")
    assert gemini.live_model() == first


def test_call_skips_resting_model_and_uses_next(monkeypatch, gemini):
    gemini._LADDERS[gemini.FAST] = ("first", "second")
    gemini._cool("first", seconds=300)

    calls = []

    class Response:
        text = "fallback response"

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs["model"])
            return Response()

    class Client:
        models = Models()

    monkeypatch.setattr(gemini, "client", lambda **_: Client())
    monkeypatch.setattr(gemini, "api_key", lambda refresh=False: "test-key")

    response = gemini.call("hello", tier=gemini.FAST)

    assert response.text == "fallback response"
    assert calls == ["second"]


def test_call_cools_unavailable_model_then_falls_back(monkeypatch, gemini):
    gemini._LADDERS[gemini.FAST] = ("unhealthy", "healthy")
    calls = []

    class Response:
        text = "healthy response"

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "unhealthy":
                raise RuntimeError("503 UNAVAILABLE")
            return Response()

    class Client:
        models = Models()

    monkeypatch.setattr(gemini, "client", lambda **_: Client())
    monkeypatch.setattr(gemini, "api_key", lambda refresh=False: "test-key")

    response = gemini.call("hello", tier=gemini.FAST)

    assert response.text == "healthy response"
    assert calls == ["unhealthy", "healthy"]
    assert gemini._cooling("unhealthy")
    assert gemini._cooldown["unhealthy"] - gemini.time.monotonic() == pytest.approx(60, abs=1)
