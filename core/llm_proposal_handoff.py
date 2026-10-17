"""One-time handoff for untrusted Text LLM action proposals.

A proposal never grants permission; it can only be forwarded to the existing
Mark executor after an explicit user confirmation supplied by the caller.
"""
from __future__ import annotations

import secrets
import time


class ProposalHandoff:
    def __init__(self):
        self._pending: dict[str, dict] = {}

    def stage(self, proposal: dict) -> str:
        if not isinstance(proposal, dict) or proposal.get("executed") is not False:
            raise ValueError("Expected a non-executed validated proposal")
        if not isinstance(proposal.get("tool"), str) or not isinstance(proposal.get("args"), dict):
            raise ValueError("Invalid proposed action")
        # Only one outstanding proposal: older plans cannot be replayed.
        self._pending.clear()
        token = secrets.token_urlsafe(24)
        self._pending[token] = {"tool": proposal["tool"], "args": dict(proposal["args"]), "at": time.monotonic()}
        return token

    def consume(self, token: str, *, approved: bool) -> dict:
        if not isinstance(token, str) or not token:
            raise ValueError("Invalid proposal token")
        proposal = self._pending.pop(token, None)
        if proposal is None:
            raise ValueError("Unknown or already consumed proposal")
        if time.monotonic() - proposal["at"] > 15.0:
            raise PermissionError("Proposal approval has expired")
        if approved is not True:
            raise PermissionError("Explicit user approval is required")
        return {"tool": proposal["tool"], "args": proposal["args"]}

    def clear(self) -> None:
        self._pending.clear()
