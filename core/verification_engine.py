"""Generic post-condition verification primitives.

This module deliberately separates *execution* from *verification*.  It can
compare observations produced by companions or WorldState, but it never turns a
successful function return into proof by itself.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any
from core.action_result import normalize, FAILED, BLOCKED, WAITING

@dataclass
class VerificationDecision:
    verified: bool
    reason: str = ""
    evidence: dict | None = None
    def to_dict(self): return asdict(self)

class GenericVerificationEngine:
    @staticmethod
    def compare(before: Any, after: Any, rule: dict | None = None) -> VerificationDecision:
        rule = dict(rule or {})
        op = str(rule.get("op") or "equals").lower()
        expected = rule.get("expected")
        ok = False
        if op == "equals": ok = after == expected
        elif op == "not_equals": ok = after != expected
        elif op == "changed": ok = before != after
        elif op == "unchanged": ok = before == after
        elif op == "contains":
            try: ok = expected in after
            except Exception: ok = False
        elif op == "exists": ok = after is not None
        else:
            return VerificationDecision(False, "unsupported_verification_operator", {"op": op})
        return VerificationDecision(ok, "" if ok else "post_condition_mismatch",
                                    {"op": op, "before": before, "after": after, "expected": expected})

    def verify_step(self, step: dict, result: Any, world, goal: dict | None = None) -> dict:
        normalized = normalize(result, capability=str(step.get("capability") or ""))
        if normalized["status"] in {FAILED, BLOCKED, WAITING}:
            return VerificationDecision(False, normalized.get("reason") or "execution_not_successful",
                                        {"action_result": normalized}).to_dict()
        check = step.get("verify") or {}
        if not check:
            return VerificationDecision(False, "independent_verification_required",
                                        {"action_result": normalized}).to_dict()
        section = check.get("section")
        if not section:
            return VerificationDecision(False, "verification_section_required", {"check": check}).to_dict()
        after = world.observed(section, None)
        if "equals" in check:
            rule = {"op":"equals","expected":check.get("equals")}
        elif "not_equals" in check:
            rule = {"op":"not_equals","expected":check.get("not_equals")}
        elif check.get("exists") is True:
            rule = {"op":"exists"}
        elif "contains" in check:
            rule = {"op":"contains","expected":check.get("contains")}
        elif check.get("changed") is True:
            before_section = check.get("before_section") or section
            before = ((goal or {}).get("execution_context") or {}).get("verification_baseline",{}).get(before_section)
            d = self.compare(before, after, {"op":"changed"})
            d.evidence = {**(d.evidence or {}), "section": section, "before_section": before_section}
            return d.to_dict()
        else:
            return VerificationDecision(False, "unsupported_verification_rule", {"check":check}).to_dict()
        d = self.compare(None, after, rule)
        d.evidence = {**(d.evidence or {}), "section": section,
                      "world_evidence": ((world.data.get("observed",{}).get(section) or {}).get("evidence"))}
        return d.to_dict()

_DEFAULT = GenericVerificationEngine()
def verify_step(step, result, world, goal=None):
    return _DEFAULT.verify_step(step, result, world, goal)
