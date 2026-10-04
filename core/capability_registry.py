from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Any
@dataclass
class Capability:
    name:str; purpose:str=""; platform:str="server"; device_id:str="server"; permissions:tuple=(); risk:str="LOW"; available:bool=True
    health:str="healthy"; dependencies:tuple=(); success_count:int=0; failure_count:int=0; source:str="builtin"
    def score(self):
        total=self.success_count+self.failure_count
        return (self.success_count/total if total else .5) + (0.2 if self.health=="healthy" else 0)
class CapabilityRegistry:
    def __init__(self): self._items={}
    def register(self,cap):
        if isinstance(cap,dict): cap=Capability(**cap)
        self._items[(cap.name,cap.device_id)]=cap; return cap
    def all(self): return [asdict(x) for x in self._items.values()]
    def select(self,name,origin_device="",requested_target="",platform="",granted_permissions=()):
        target=requested_target or origin_device or ""
        allowed=set(granted_permissions or ())
        cands=[c for c in self._items.values() if c.name==name and c.available and c.health!="offline"]
        if platform:cands=[c for c in cands if c.platform==platform]
        cands=[c for c in cands if set(c.permissions).issubset(allowed)]
        if target:
            local=[c for c in cands if c.device_id==target]
            if local:cands=local
        return max(cands,key=lambda c:c.score(),default=None)
    def record(self,name,device_id,success):
        c=self._items.get((name,device_id))
        if c:
            if success:c.success_count+=1
            else:c.failure_count+=1
def build_registry(server_actions=(),devices=()):
    r=CapabilityRegistry()
    for name in server_actions:r.register(Capability(name=name,purpose=f"Server action {name}",risk="HIGH" if name=="self_repair_apply" else "MEDIUM",permissions=()))
    for d in devices:
        did=str(d.get("device_id","")); online=bool(d.get("online",False)); platform=str(d.get("platform") or d.get("kind") or "companion")
        for name in d.get("capabilities",[]) or []:r.register(Capability(name=str(name),purpose="Companion capability",platform=platform,device_id=did,permissions=(str(name),),available=online,health="healthy" if online else "offline",source="companion"))
    return r
