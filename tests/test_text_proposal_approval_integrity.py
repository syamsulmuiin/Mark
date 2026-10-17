import pytest
from core import llm_proposal_handoff as module


def test_expired_proposal_cannot_execute(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    handoff = module.ProposalHandoff()
    token = handoff.stage({"tool": "open_app", "args": {}, "executed": False})
    clock[0] += 16.0
    with pytest.raises(PermissionError, match="expired"):
        handoff.consume(token, approved=True)
    with pytest.raises(ValueError):
        handoff.consume(token, approved=True)


def test_main_rejects_truncated_approval_details():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'if len(_args_preview) > 3000:' in source
    assert 'if confirm_gate.pending_request() is not None:' in source
    assert 'self._text_proposal_handoff.clear()' in source
    assert '[:3000]' not in source[source.index('if name == "propose_text_action":'):source.index('if name == "plan_with_text_llm":')]
