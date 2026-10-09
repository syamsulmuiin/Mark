from __future__ import annotations
from dataclasses import dataclass,asdict,field
from typing import Any

@dataclass
class Capability:
    name:str
    purpose:str=""
    platform:str="server"
    device_id:str="server"
    permissions:tuple=()
    risk:str="LOW"
    available:bool=True
    health:str="healthy"
    dependencies:tuple=()
    success_count:int=0
    failure_count:int=0
    verified_count:int=0
    unverified_count:int=0
    source:str="builtin"
    avg_latency_ms:float=0.0
    last_error:str=""
    metadata:dict=field(default_factory=dict)

    def score(self):
        total=self.success_count+self.failure_count
        success=(self.success_count/total if total else .5)
        health_bonus=.2 if self.health=="healthy" else -.2 if self.health in {"degraded","offline"} else 0
        latency_penalty=min(max(self.avg_latency_ms,0.0)/10000.0,.15)
        verification_total=self.verified_count+self.unverified_count
        verification_bonus=(self.verified_count/verification_total)*.10 if verification_total else 0.0
        return success+health_bonus+verification_bonus-latency_penalty

class CapabilityRegistry:
    def __init__(self): self._items={}
    def register(self,cap):
        if isinstance(cap,dict):
            cap=dict(cap)
            for key in ("permissions","dependencies"):
                if key in cap and not isinstance(cap[key],tuple):cap[key]=tuple(cap[key] or ())
            cap=Capability(**cap)
        self._items[(cap.name,cap.device_id)]=cap; return cap
    def all(self): return [asdict(x) for x in self._items.values()]
    def get(self,name,device_id="server"):return self._items.get((name,device_id))

    def candidates(self,name,origin_device="",requested_target="",platform="",granted_permissions=(),exclude_device_ids=()):
        target=requested_target or origin_device or ""
        allowed=set(granted_permissions or ()); excluded=set(exclude_device_ids or ())
        cands=[c for c in self._items.values() if c.name==name and c.available and c.health!="offline" and c.device_id not in excluded]
        if platform:cands=[c for c in cands if c.platform==platform]
        cands=[c for c in cands if set(c.permissions).issubset(allowed)]
        if target:
            local=[c for c in cands if c.device_id==target]
            if local:cands=local
        return sorted(cands,key=lambda c:c.score(),reverse=True)

    def select(self,name,origin_device="",requested_target="",platform="",granted_permissions=(),exclude_device_ids=()):
        cands=self.candidates(name,origin_device,requested_target,platform,granted_permissions,exclude_device_ids)
        return cands[0] if cands else None

    def record(self,name,device_id,success,latency_ms=0,error="",verified=None):
        c=self._items.get((name,device_id))
        if c:
            if success:c.success_count+=1
            else:c.failure_count+=1
            if success and verified is not None:
                if bool(verified):c.verified_count+=1
                else:c.unverified_count+=1
            if latency_ms:
                total=max(1,c.success_count+c.failure_count)
                previous=max(0,total-1)
                c.avg_latency_ms=((c.avg_latency_ms*previous)+float(latency_ms))/total
            if error:c.last_error=str(error)[:500]
            # Do not silently mark a device offline from a single action failure.
            # Repeated failures degrade routing preference while preserving availability.
            if c.failure_count>=3 and c.failure_count>c.success_count:c.health="degraded"
            if success and c.health=="degraded" and c.success_count>=c.failure_count:c.health="healthy"


def _capability_name_and_meta(item):
    if isinstance(item,dict):
        name=str(item.get("name") or item.get("capability") or "").strip()
        return name,{k:v for k,v in item.items() if k not in {"name","capability"}}
    return str(item).strip(),{}


def build_registry(server_actions=(),devices=()):
    r=CapabilityRegistry()
    for name in server_actions:
        r.register(Capability(name=name,purpose=f"Server action {name}",risk="HIGH" if name=="self_repair_apply" else "MEDIUM",permissions=()))
    for d in devices:
        did=str(d.get("device_id","")); online=bool(d.get("online",False)); platform=str(d.get("platform") or d.get("kind") or "companion")
        manifest=d.get("capability_manifest") if isinstance(d.get("capability_manifest"),dict) else {}
        health_map=d.get("capability_health") if isinstance(d.get("capability_health"),dict) else {}
        for item in d.get("capabilities",[]) or []:
            name,meta=_capability_name_and_meta(item)
            if not name:continue
            merged={**(manifest.get(name) if isinstance(manifest.get(name),dict) else {}),**meta,**(health_map.get(name) if isinstance(health_map.get(name),dict) else {})}
            r.register(Capability(name=name,purpose=str(merged.get("purpose") or "Companion capability"),platform=platform,device_id=did,
                                  permissions=(name,),available=online,health=str(merged.get("health") or ("healthy" if online else "offline")),source="companion",
                                  success_count=int(merged.get("success_count") or 0),failure_count=int(merged.get("failure_count") or 0),
                                  verified_count=int(merged.get("verified_count") or 0),unverified_count=int(merged.get("unverified_count") or 0),
                                  avg_latency_ms=float(merged.get("avg_latency_ms") or 0),last_error=str(merged.get("last_error") or ""),metadata=merged))
    return r
