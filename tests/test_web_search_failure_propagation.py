import importlib


def test_grounding_quota_from_failed_ladder_trips_websearch_breaker(monkeypatch):
    web = importlib.import_module("actions.web_search")
    gemini = importlib.import_module("core.gemini")
    web._quota_blocked_until = 0.0
    monkeypatch.setattr(gemini, "call", lambda *a, **k: None)
    monkeypatch.setattr(gemini, "last_call_errors", lambda: (("model-a", "429 RESOURCE_EXHAUSTED"),))
    try:
        web._gemini_search("test")
        raise AssertionError("expected failed grounding")
    except RuntimeError as exc:
        assert "429 RESOURCE_EXHAUSTED" in str(exc)
    assert not web._gemini_available()
