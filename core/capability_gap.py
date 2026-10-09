"""Resolve missing capabilities without immediately declaring a goal impossible."""
from __future__ import annotations
from dataclasses import dataclass, asdict

@dataclass
class GapResolution:
    state: str
    capability: str
    skill_id: str = ""
    reason: str = ""
    evidence: dict | None = None
    def to_dict(self): return asdict(self)

class CapabilityGapResolver:
    def __init__(self, capabilities, skills=None):
        self.capabilities = capabilities
        self.skills = skills

    def resolve(self, name: str, *, origin_device: str = "", requested_target: str = "",
                platform: str = "", granted_permissions=(), allow_evolution: bool = False):
        cap = self.capabilities.select(name, origin_device, requested_target, platform, granted_permissions)
        if cap:
            return GapResolution("AVAILABLE", name, evidence={"device_id": cap.device_id, "source": cap.source})
        if self.skills is not None:
            candidates = self.skills.find_for_capability(name, executable_only=True)
            if candidates:
                # Planner v2: trust first, then measured reliability/latency, low risk
                # and fewer steps.  No model call is involved in this selection.
                rank = {"TRUSTED": 4, "VERIFIED": 3, "CANDIDATE": 2, "EXPERIMENTAL": 1}
                risk_penalty={"LOW":0.0,"MEDIUM":0.15,"HIGH":1.0}
                def plan_score(r):
                    m=r.get("metrics") or {}; ok=int(m.get("success_count",0)); bad=int(m.get("failure_count",0)); total=ok+bad
                    reliability=(ok/total) if total else .5
                    times=[float(x) for x in (m.get("execution_time") or [])[-20:] if isinstance(x,(int,float))]
                    latency_penalty=min((sum(times)/len(times))/30.0,.20) if times else 0.0
                    step_penalty=min(len(r.get("steps") or [])*.015,.15)
                    return rank.get(r.get("status",""),0)+reliability-latency_penalty-step_penalty-risk_penalty.get(str(r.get("risk_level","LOW")).upper(),.5)
                candidates.sort(key=plan_score, reverse=True)
                chosen = candidates[0]
                return GapResolution("COMPOSITE_AVAILABLE", name, chosen["skill_id"],
                                     evidence={"skill": chosen.get("name"), "status": chosen.get("status"),
                                               "planner":"v2","score":round(plan_score(chosen),6),
                                               "candidate_count":len(candidates)})
        if allow_evolution:
            return GapResolution("EVOLUTION_ELIGIBLE", name, reason="no_existing_capability_or_composite")
        return GapResolution("UNRESOLVED", name, reason="no_safe_existing_capability")
