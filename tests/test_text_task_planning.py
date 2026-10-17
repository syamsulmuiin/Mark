"""Planning stays on the configured text provider and cannot execute actions."""
import json
import pytest
from core import llm_text


def test_plan_uses_selected_provider_and_is_not_executed(monkeypatch):
    calls = []
    def fake_generate(prompt, *, config=None):
        calls.append((prompt, config))
        return json.dumps({"summary": "Open a website", "steps": ["Inspect site", "Open page"]})
    monkeypatch.setattr(llm_text, "generate", fake_generate)
    result = llm_text.plan("Open example", config={"llm_provider": "deepseek"})
    assert result == {"summary": "Open a website", "steps": ["Inspect site", "Open page"], "executed": False}
    assert calls[0][1] == {"llm_provider": "deepseek"}


@pytest.mark.parametrize("response", [
    "not json", "{}", '{"summary":"x","steps":[]}',
    '{"summary":"x","steps":["a"],"executed":true}',
    '{"summary":"x","steps":[42]}',
])
def test_invalid_plan_rejected(monkeypatch, response):
    monkeypatch.setattr(llm_text, "generate", lambda *a, **k: response)
    with pytest.raises(ValueError):
        llm_text.plan("task")
