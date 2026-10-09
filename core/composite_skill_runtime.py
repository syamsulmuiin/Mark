"""Execute declarative SkillRegistry compositions using existing capabilities only."""
from __future__ import annotations
import time
from core.action_result import normalize, SUCCESS, FAILED, UNVERIFIED, BLOCKED

class CompositeSkillRuntime:
    def __init__(self, capabilities, skills, executor):
        self.capabilities = capabilities
        self.skills = skills
        self.executor = executor

    def execute(self, skill_id: str, goal: dict, *, origin_device: str = "",
                requested_target: str = "", granted_permissions=()) -> dict:
        skill = self.skills.get(skill_id)
        if skill.get("skill_type", "COMPOSITE") != "COMPOSITE":
            return {"status": FAILED, "verified": False, "reason": "not_a_composite_skill", "skill_id": skill_id}
        if skill.get("status") not in {"VERIFIED", "TRUSTED"}:
            return {"status": BLOCKED, "verified": False,
                    "reason": "skill_not_verified", "skill_id": skill_id}
        started = time.monotonic(); evidence=[]; context={}
        for index, step in enumerate(skill.get("steps") or []):
            name = str(step.get("capability") or "")
            cap = self.capabilities.select(name, origin_device, requested_target,
                                           step.get("platform", ""), granted_permissions)
            if not cap:
                self.skills.record(skill_id, False, time.monotonic()-started,
                                   failure=f"capability_unavailable:{name}")
                return {"status": FAILED, "verified": False, "reason": "capability_unavailable",
                        "capability": name, "step": index, "evidence": evidence, "skill_id": skill_id}
            raw = self.executor(cap, dict(step.get("inputs") or {}), goal)
            result = normalize(raw, capability=name)
            evidence.append({"step": index, "capability": name, "device_id": cap.device_id, "result": result})
            context[name] = result.get("result")
            if result["status"] in {FAILED, "BLOCKED", "WAITING"}:
                self.capabilities.record(name, cap.device_id, False)
                self.skills.record(skill_id, False, time.monotonic()-started,
                                   failure=result.get("reason") or result["status"])
                return {"status": result["status"], "verified": False,
                        "reason": result.get("reason") or "composite_step_failed",
                        "step": index, "evidence": evidence, "skill_id": skill_id}
            self.capabilities.record(name, cap.device_id, True, verified=result.get("verified") is True)
        all_verified = bool(evidence) and all(x["result"].get("verified") is True for x in evidence)
        status = SUCCESS if all_verified else UNVERIFIED
        self.skills.record(skill_id, all_verified, time.monotonic()-started,
                           failure="" if all_verified else "composite_post_condition_unverified")
        return {"status": status, "verified": all_verified, "result": context,
                "evidence": evidence, "skill_id": skill_id,
                "reason": "" if all_verified else "composite_post_condition_unverified"}
