"""Capability routing is explicit, bounded and never replays uncertain image jobs."""

import json
import pytest
from core import model_profiles as routing


def config():
    return {
        "model_routing": {
            "enabled": True,
            "profiles": [
                {
                    "id": "first",
                    "provider": "openai",
                    "model": "test-a",
                    "capabilities": ["text", "vision"],
                    "api_key": "secret-a",
                },
                {
                    "id": "second",
                    "provider": "anthropic",
                    "model": "test-b",
                    "capabilities": ["text"],
                    "api_key": "secret-b",
                },
            ],
            "routes": {"text": ["first", "second"], "vision": ["first"]},
            "failover": ["text"],
        }
    }


@pytest.fixture(autouse=True)
def private_logs(tmp_path, monkeypatch):
    from core import setup_config

    monkeypatch.setattr(setup_config, "BASE_DIR", tmp_path)


def test_only_approved_order_and_remaining_budget():
    calls = []

    def invoke(profile, remaining):
        calls.append((profile["id"], remaining))
        if profile["id"] == "first":
            raise RuntimeError("openai HTTP 503")
        return "done"

    assert routing.run("text", invoke, settings=config(), timeout=10) == "done"
    assert [c[0] for c in calls] == ["first", "second"]
    assert 0 < calls[1][1] <= calls[0][1] <= 10


@pytest.mark.parametrize(
    "error",
    [RuntimeError("refusal"), ValueError("malformed JSON"), RuntimeError("HTTP 403")],
)
def test_ambiguous_or_refused_requests_are_not_retried(error):
    calls = []

    def invoke(profile, remaining):
        calls.append(profile["id"])
        raise error

    with pytest.raises(type(error)):
        routing.run("text", invoke, settings=config())
    assert calls == ["first"]


def test_failover_requires_explicit_opt_in():
    cfg = config()
    cfg["model_routing"]["failover"] = []
    calls = []

    def invoke(profile, remaining):
        calls.append(profile["id"])
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        routing.run("text", invoke, settings=cfg)
    assert calls == ["first"]


@pytest.mark.parametrize(
    "message,allowed",
    [
        ("image_provider_http_429", True),
        ("image_provider_http_401", True),
        ("image_provider_http_500", False),
        ("image_provider_http_403", False),
        ("image_provider_pending", False),
        ("timed out", False),
    ],
)
def test_image_replay_policy(message, allowed):
    assert routing._safe_next("image", RuntimeError(message)) is allowed


@pytest.mark.parametrize("role", ["audio", "video", "image"])
def test_missing_capability_is_blocked(role):
    with pytest.raises(routing.RouteUnavailable):
        routing.candidates(role, config())


def test_incompatible_route_rejected():
    cfg = config()
    cfg["model_routing"]["routes"]["vision"] = ["second"]
    with pytest.raises(ValueError):
        routing.validate(cfg["model_routing"])


def test_live_failover_rejected():
    cfg = config()["model_routing"]
    cfg["profiles"] = [
        {"id": i, "provider": "gemini", "model": "live-test", "capabilities": ["live"]}
        for i in ("one", "two")
    ]
    cfg["routes"] = {"live": ["one", "two"]}
    with pytest.raises(ValueError, match="Live"):
        routing.validate(cfg)


def test_snapshot_never_contains_credentials():
    assert "secret-" not in json.dumps(routing.snapshot(config()))
    assert routing.snapshot({})["enabled"] is False


def test_malformed_provider_is_validation_error():
    cfg = config()["model_routing"]
    cfg["profiles"][0]["provider"] = []
    with pytest.raises(ValueError):
        routing.validate(cfg)


def test_atomic_save_preserves_other_configuration(tmp_path, monkeypatch):
    from core import setup_config

    path = tmp_path / "settings.json"
    path.write_text('{"unrelated":42}')
    monkeypatch.setattr(setup_config, "CONFIG_FILE", path)
    routing.save(config()["model_routing"])
    assert json.loads(path.read_text())["unrelated"] == 42
    assert path.stat().st_mode & 0o077 == 0


def test_legacy_import_does_not_authorize_previous_fallbacks():
    cfg = routing.from_legacy(
        {
            "llm_provider": "deepseek",
            "provider_models": {"deepseek": "primary,old-fallback"},
            "live_provider": "gemini",
            "live_models": "voice-primary,voice-fallback",
        }
    )
    assert cfg["profiles"][0]["model"] == "primary"
    assert cfg["profiles"][1]["model"] == "voice-primary"
    assert cfg["failover"] == []


def test_profile_key_is_forwarded_without_legacy_key(monkeypatch):
    from core import profile_execution, llm_compatible

    seen = {}

    def generate(provider, model, prompt, **kwargs):
        seen.update(provider=provider, model=model, **kwargs)
        return "ok"

    monkeypatch.setattr(llm_compatible, "generate_text", generate)
    monkeypatch.setattr(profile_execution, "traced_text_call", lambda p, m, fn: fn())
    profile = config()["model_routing"]["profiles"][0]
    assert (
        profile_execution.infer(profile, "hello", settings={"openai_api_key": "wrong"})
        == "ok"
    )
    assert seen["api_key"] == "secret-a"
    assert seen["model"] == "test-a"


def test_identity_handles_unassigned_live_route():
    from core.llm_identity import identity_instruction

    text = identity_instruction(config(), role="Text", text_model="test-a")
    assert "not configured" in text
    assert "secret-" not in text


def test_live_profile_precedes_legacy(monkeypatch):
    from core import llm_live

    cfg = config()
    p = cfg["model_routing"]
    p["profiles"].append(
        {
            "id": "voice",
            "provider": "openai_realtime",
            "model": "selected-live",
            "capabilities": ["live"],
            "api_key": "voice-key",
        }
    )
    p["routes"]["live"] = ["voice"]
    cfg["live_provider"] = "gemini"
    assert llm_live.provider(cfg) == "openai_realtime"
    assert llm_live.model(cfg) == "selected-live"
    assert llm_live.note_model_failure("selected-live", "failure", cfg) is False


def test_image_router_does_not_retry_pending(tmp_path, monkeypatch):
    from core import image_generation

    cfg = config()
    p = cfg["model_routing"]
    for identifier in ("img_one", "img_two"):
        p["profiles"].append(
            {
                "id": identifier,
                "provider": "openai",
                "model": "gpt-image-test",
                "capabilities": ["image"],
                "api_key": "private",
            }
        )
    p["routes"]["image"] = ["img_one", "img_two"]
    p["failover"].append("image")
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs["config"])
        raise image_generation.ImageGenerationPending(
            "image_generation_timeout_result_unknown"
        )

    monkeypatch.setattr(image_generation, "_generate_image", generate)
    with pytest.raises(image_generation.ImageGenerationPending):
        image_generation.generate_image("test", tmp_path, config=cfg)
    assert len(calls) == 1


def test_configured_uses_profile_credentials(monkeypatch):
    from core import setup_config

    cfg = config()
    cfg["os_system"] = "linux"
    cfg["model_routing"]["profiles"].append(
        {
            "id": "voice",
            "provider": "gemini",
            "model": "voice-model",
            "capabilities": ["live"],
            "api_key": "profile-only",
        }
    )
    cfg["model_routing"]["routes"]["live"] = ["voice"]
    monkeypatch.setattr(setup_config, "load_config", lambda: cfg)
    assert setup_config.configured() is True


def test_text_route_reports_actual_alternative_identity(monkeypatch):
    from core import chat_router, profile_execution

    calls = []

    def infer(profile, prompt, **kwargs):
        calls.append((profile["id"], prompt))
        if profile["id"] == "first":
            raise RuntimeError("openai HTTP 429")
        return "answer"

    monkeypatch.setattr(profile_execution, "infer", infer)
    assert chat_router.generate_chat_text("question", config=config()) == "answer"
    assert "test-b" in calls[1][1] and "Anthropic Claude API" in calls[1][1]
    assert "secret-" not in calls[1][1]


def test_expired_budget_does_not_invoke_provider(monkeypatch):
    seen = []
    with pytest.raises(TimeoutError):
        routing.run(
            "text", lambda *args: seen.append(args), settings=config(), timeout=0
        )
    assert not seen


def test_gemini_profile_uses_fixed_endpoint_and_own_key(monkeypatch):
    from core import profile_execution

    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"parts": [{"text": "answer"}]},
                        }
                    ]
                }
            ).encode()

    def urlopen(request, **kwargs):
        seen.update(
            url=request.full_url,
            headers=dict(request.header_items()),
            body=json.loads(request.data),
        )
        return Response()

    monkeypatch.setattr(profile_execution, "urlopen", urlopen)
    monkeypatch.setattr(profile_execution, "traced_text_call", lambda p, m, fn: fn())
    profile = {"provider": "gemini", "model": "selected-test", "api_key": "profile-key"}
    assert profile_execution.infer(profile, "question", images=["YWJj"]) == "answer"
    assert (
        seen["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/selected-test:generateContent"
    )
    assert seen["headers"]["X-goog-api-key"] == "profile-key"
    assert seen["body"]["contents"][0]["parts"][1]["inlineData"]["data"] == "YWJj"


def test_cancel_wizard_does_not_save(monkeypatch):
    monkeypatch.setattr(routing, "load_config", config)
    monkeypatch.setattr("builtins.input", lambda prompt: "4")
    monkeypatch.setattr(
        routing, "save", lambda *args: pytest.fail("Cancellation must not save")
    )
    routing.configure()
