"""OpenAI-compatible adapter tests use a fake transport, never real API calls."""
import json
import pytest
from core import llm_compatible as adapter


@pytest.mark.parametrize("provider", ["openai", "deepseek", "openrouter", "ollama_cloud", "ollama_local"])
def test_openai_compatible_payload(monkeypatch, provider):
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return json.dumps({
            "choices": [{"message": {"content": "Halo"}}]
        }).encode()
    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data)
        return Response()
    monkeypatch.setattr(adapter, "urlopen", fake_open)
    assert adapter.generate_text(provider, "test-model", "Halo", api_key="secret") == "Halo"
    assert captured["url"] == adapter.ENDPOINTS[provider]
    assert captured["auth"] == "Bearer secret"
    assert captured["payload"]["stream"] is False


def test_no_remote_request_without_key(monkeypatch):
    monkeypatch.setattr(adapter, "urlopen", lambda *a, **kw: pytest.fail("network called"))
    with pytest.raises(ValueError):
        adapter.generate_text("openrouter", "example", "hello")


def test_reject_custom_remote_endpoints():
    with pytest.raises(ValueError):
        adapter.generate_text("openai", "model", "hello", api_key="key",
                              endpoint="https://example.com/steal")


def test_local_ollama_only_allows_loopback():
    with pytest.raises(ValueError):
        adapter.generate_text("ollama_local", "llama3", "hello",
                              endpoint="http://192.168.1.5:11434/v1/chat/completions")
