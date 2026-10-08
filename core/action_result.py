"""Structured execution results shared by server autonomy and native companions.

The legacy wire contract (``ok`` + ``result``) remains valid.  New code should
also provide ``status``, ``verified`` and ``evidence`` so a successful function
return is never confused with an independently observed post-condition.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

SUCCESS = "SUCCESS"
FAILED = "FAILED"
UNVERIFIED = "UNVERIFIED"
WAITING = "WAITING"
BLOCKED = "BLOCKED"
STATUSES = {SUCCESS, FAILED, UNVERIFIED, WAITING, BLOCKED}

@dataclass
class ActionResult:
    status: str
    result: Any = None
    verified: bool = False
    evidence: Any = None
    reason: str = ""
    capability: str = ""
    operation_id: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.status in {SUCCESS, UNVERIFIED}
        return d


def make(status: str, result: Any = None, *, verified: bool = False,
         evidence: Any = None, reason: str = "", capability: str = "",
         operation_id: str = "") -> dict:
    status = str(status or UNVERIFIED).upper()
    if status not in STATUSES:
        raise ValueError(f"invalid action status: {status}")
    if verified and status != SUCCESS:
        raise ValueError("only SUCCESS may be verified")
    return ActionResult(status, result, bool(verified), evidence, str(reason or ""),
                        str(capability or ""), str(operation_id or "")).to_dict()


def normalize(value: Any, *, capability: str = "") -> dict:
    """Normalize old and new action results without inventing verification.

    A legacy ``ok=True`` means only that transport/execution returned; it is
    intentionally classified as UNVERIFIED unless the caller supplied explicit
    verification evidence.
    """
    if isinstance(value, dict):
        status = str(value.get("status") or "").upper()
        if status in STATUSES:
            out = dict(value)
            out.setdefault("verified", status == SUCCESS and bool(value.get("verified")))
            out.setdefault("evidence", None)
            out.setdefault("reason", "")
            out.setdefault("capability", capability)
            out.setdefault("ok", status in {SUCCESS, UNVERIFIED})
            if out.get("verified") and status != SUCCESS:
                out["verified"] = False
            return out
        if value.get("ok") is False:
            return make(FAILED, value.get("result"), evidence=value.get("evidence"),
                        reason=value.get("reason") or value.get("error") or "execution_failed",
                        capability=capability)
        if value.get("verified") is True:
            return make(SUCCESS, value.get("result"), verified=True,
                        evidence=value.get("evidence"), capability=capability)
        return make(UNVERIFIED, value.get("result", value), capability=capability,
                    evidence=value.get("evidence"), reason=value.get("reason") or "post_condition_not_verified")
    return make(UNVERIFIED, value, capability=capability,
                reason="legacy_result_without_post_condition")
