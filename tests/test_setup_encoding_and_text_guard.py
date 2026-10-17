"""Regression checks for setup, Claude routing and Live action guard."""
from pathlib import Path
import io
import sys
from core import setup_config, chat_router


def test_safe_input_replaces_invalid_utf8(monkeypatch):
    fake = io.TextIOWrapper(io.BytesIO(bytes([53, 255, 10])), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", fake)
    assert setup_config._safe_input("Provider: ").startswith("5")


def test_claude_routing(monkeypatch):
    monkeypatch.setattr(chat_router, "generate_claude_text", lambda model, prompt, api_key, **kwargs: model + ":" + prompt)
    result = chat_router.generate_chat_text("hello", config={
        "llm_provider": "anthropic", "chat_models": "claude-test", "anthropic_api_key": "secret"
    })
    assert result == "claude-test:hello"


def test_live_action_requires_host_approval_and_resets_context(monkeypatch):
    import ast
    import asyncio
    from types import SimpleNamespace
    from core.llm_proposal_handoff import ProposalHandoff

    tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "JarvisLive")
    methods = [n for n in cls.body if getattr(n, "name", "") in {
        "_execute_tool", "execute_approved_text_proposal"}]
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        ast.ClassDef(name="Runtime", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
    writes = []
    import json
    namespace = {"json": json, "_trace_event": lambda *a, **k: None, "types": SimpleNamespace(FunctionResponse=lambda **kw: SimpleNamespace(**kw)),
                 "update_memory": writes.append}
    exec(compile(ast.fix_missing_locations(module), "runtime", "exec"), namespace)
    runtime = namespace["Runtime"]()
    runtime.ui = SimpleNamespace(set_state=lambda state: None, muted=True)
    from core import action_policy
    # Exercise the authorization boundary independently of the risk classifier.
    monkeypatch.setattr(action_policy, "requires_confirmation", lambda name, args: True)
    runtime._text_proposal_handoff = ProposalHandoff()
    args = {"key": "test", "value": "ok", "user_approved": True}
    action = SimpleNamespace(id=None, name="save_memory", args=args)

    async def scenario():
        rejected = await runtime._execute_tool(action)
        assert rejected.response["executed"] is False
        assert writes == []
        token = runtime._text_proposal_handoff.stage({"tool": "save_memory", "args": args, "executed": False})
        accepted = await runtime.execute_approved_text_proposal(token, user_approved=True)
        assert accepted.response["result"] == "ok"
        assert len(writes) == 1
        assert runtime._approved_text_action_context.get() is False
        rejected_again = await runtime._execute_tool(action)
        assert rejected_again.response["executed"] is False
        assert len(writes) == 1
    asyncio.run(scenario())
