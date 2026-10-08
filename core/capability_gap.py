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
                # Prefer the most trusted lifecycle stage, then the most successful.
                rank = {"TRUSTED": 4, "VERIFIED": 3, "CANDIDATE": 2, "EXPERIMENTAL": 1}
                candidates.sort(key=lambda r: (
                    rank.get(r.get("status", ""), 0),
                    int((r.get("metrics") or {}).get("success_count", 0)) - int((r.get("metrics") or {}).get("failure_count", 0)),
                ), reverse=True)
                chosen = candidates[0]
                return GapResolution("COMPOSITE_AVAILABLE", name, chosen["skill_id"],
                                     evidence={"skill": chosen.get("name"), "status": chosen.get("status")})
        if allow_evolution:
            return GapResolution("EVOLUTION_ELIGIBLE", name, reason="no_existing_capability_or_composite")
        return GapResolution("UNRESOLVED", name, reason="no_safe_existing_capability")
