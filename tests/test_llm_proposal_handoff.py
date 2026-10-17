import pytest
from core.llm_proposal_handoff import ProposalHandoff


def test_requires_explicit_approval_and_is_single_use():
    handoff = ProposalHandoff()
    token = handoff.stage({"tool": "open_app", "args": {"name": "browser"}, "executed": False})
    with pytest.raises(PermissionError):
        handoff.consume(token, approved=False)
    with pytest.raises(ValueError):
        handoff.consume(token, approved=True)


def test_approved_proposal_can_be_consumed_once():
    handoff = ProposalHandoff()
    token = handoff.stage({"tool": "open_app", "args": {"name": "browser"}, "executed": False})
    assert handoff.consume(token, approved=True) == {"tool": "open_app", "args": {"name": "browser"}}
    with pytest.raises(ValueError):
        handoff.consume(token, approved=True)


def test_new_proposal_invalidates_old_token():
    handoff = ProposalHandoff()
    first = handoff.stage({"tool": "a", "args": {}, "executed": False})
    second = handoff.stage({"tool": "b", "args": {}, "executed": False})
    with pytest.raises(ValueError):
        handoff.consume(first, approved=True)
    assert handoff.consume(second, approved=True)["tool"] == "b"


def test_rejects_unvalidated_or_already_executed_proposal():
    handoff = ProposalHandoff()
    with pytest.raises(ValueError):
        handoff.stage({"tool": "a", "args": {}, "executed": True})
