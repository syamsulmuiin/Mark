import json
import pytest
from core.llm_action_proposals import propose_action, validate_proposal


def test_valid_registry_tool_is_proposed_not_executed(monkeypatch):
    import core.llm_text as llm_text
    monkeypatch.setattr(llm_text, "generate", lambda prompt, config=None: json.dumps({
        "tool": "open_app", "args": {"name": "browser"}, "reason": "User requested browser"
    }))
    result = propose_action("open browser", [{"name": "open_app"}], config={"llm_provider": "deepseek"})
    assert result["tool"] == "open_app"
    assert result["executed"] is False


@pytest.mark.parametrize("raw", [
    '{"tool":"unknown","args":{},"reason":"test"}',
    '{"tool":"open_app","args":{},"reason":"test","approved":true}',
    '{"tool":"open_app","args":[],"reason":"test"}',
    '{"tool":"open_app","args":{},"reason":""}',
    "not json",
])
def test_rejects_invalid_or_unauthorized_proposals(raw):
    with pytest.raises(ValueError):
        validate_proposal(raw, {"open_app"})


def test_delegation_tools_are_not_available_to_proposer(monkeypatch):
    import core.llm_text as llm_text
    monkeypatch.setattr(llm_text, "generate", lambda prompt, config=None: '{"tool":"delegate_to_text_llm","args":{},"reason":"loop"}')
    with pytest.raises(ValueError):
        propose_action("do task", [{"name":"delegate_to_text_llm"},{"name":"open_app"}])


def test_proposer_receives_argument_schema(monkeypatch):
    import core.llm_text as llm_text
    schema = {"name": "browser_control", "description": "Control the browser",
              "parameters": {"type": "object", "properties": {
                  "action": {"type": "string"}, "url": {"type": "string"}},
                  "required": ["action", "url"]}}
    prompts = []
    def generate(prompt, config=None):
        prompts.append(prompt)
        return json.dumps({"tool": "browser_control", "args": {
            "action": "open", "url": "https://example.com"}, "reason": "Requested"})
    monkeypatch.setattr(llm_text, "generate", generate)
    result = propose_action("open example.com", [schema])
    assert json.dumps(schema) in prompts[0]
    assert result["args"]["url"] == "https://example.com"
    assert result["executed"] is False
