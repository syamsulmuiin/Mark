"""The existing trusted confirmation gate mediates Text LLM actions."""
from pathlib import Path
from core.llm_proposal_handoff import ProposalHandoff


def test_main_uses_existing_confirmation_gate_for_text_proposals():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'key="text_proposal:" + _proposal_key' in source
    assert "confirm_gate.request," in source
    assert "asyncio.run_coroutine_threadsafe(" in source
    assert "self.execute_approved_text_proposal(" in source
    assert "user_approved=True" in source


def test_handoff_rejects_replay_after_approval():
    gate = ProposalHandoff()
    token = gate.stage({"tool": "open_app", "args": {}, "executed": False})
    assert gate.consume(token, approved=True)["tool"] == "open_app"
    try:
        gate.consume(token, approved=True)
    except ValueError:
        pass
    else:
        raise AssertionError("Replayed proposal must fail")
