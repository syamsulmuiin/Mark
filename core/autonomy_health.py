from __future__ import annotations
class HealthMonitor:
    def __init__(self,world,memory=None):self.world=world;self.memory=memory
    def anomalies(self):
        out=[]
        for section,entry in self.world.data.get("observed",{}).items():
            v=entry.get("value")
            if isinstance(v,dict) and v.get("health") in {"failed","offline","degraded"}:out.append({"component":section,"observed":v,"evidence":entry.get("evidence","")})
        return out
    def recovery_candidate(self,anomaly):
        if not self.memory:return None
        q=f"{anomaly.get('component')} {anomaly.get('observed')}"
        for r in self.memory.search(q,verified_only=True):
            if r.get("type")=="procedural" and (r.get("environment") or {}).get("risk")=="LOW":return r
        return None
