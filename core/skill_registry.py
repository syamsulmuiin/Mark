from __future__ import annotations
import json,os,uuid
from datetime import datetime,timezone
from pathlib import Path
def _now():return datetime.now(timezone.utc).isoformat(timespec="seconds")
class SkillRegistry:
    def __init__(self,base_dir):
        self.dir=Path(base_dir)/"skills"; self.dir.mkdir(parents=True,exist_ok=True)
    def create(self,name,purpose,steps,permissions=(),risk_level="LOW",platforms=(),knowledge_reference=()):
        if not steps:raise ValueError("skill requires steps")
        if any(not isinstance(s,dict) or not s.get("capability") for s in steps):raise ValueError("skills are declarative capability compositions")
        r={"skill_id":uuid.uuid4().hex,"name":name,"purpose":purpose,"steps":steps,"permissions":list(permissions),"risk_level":risk_level,
           "supported_platforms":list(platforms),"knowledge_reference":list(knowledge_reference),"status":"EXPERIMENTAL","history":[],
           "metrics":{"success_count":0,"failure_count":0,"rollback_count":0,"failure_patterns":[],"execution_time":[],"environments_tested":[],"last_validation":None,"known_limitations":[]},"created_at":_now()}
        self._save(r);return r
    def _save(self,r):
        p=self.dir/f"{r['skill_id']}.json";t=p.with_suffix(".tmp");t.write_text(json.dumps(r,indent=2),encoding="utf-8");os.replace(t,p)
    def get(self,sid):return json.loads((self.dir/f"{sid}.json").read_text(encoding="utf-8"))
    def promote(self,sid,target,validation, human_approved=False):
        r=self.get(sid); order={"EXPERIMENTAL":0,"CANDIDATE":1,"VERIFIED":2,"TRUSTED":3,"DEPRECATED":-1}
        if target=="TRUSTED" and not human_approved:raise PermissionError("TRUSTED promotion requires human approval")
        if target not in order:raise ValueError("invalid status")
        if target!="DEPRECATED" and order[target]>order.get(r["status"],0)+1:raise ValueError("cannot skip lifecycle stage")
        if target in {"CANDIDATE","VERIFIED","TRUSTED"} and not validation:raise ValueError("validation evidence required")
        r["history"].append({"from":r["status"],"to":target,"at":_now(),"validation":validation});r["status"]=target;r["metrics"]["last_validation"]=_now();self._save(r);return r
    def record(self,sid,success,elapsed=0,failure=""):
        r=self.get(sid);m=r["metrics"];m["success_count" if success else "failure_count"]+=1
        if elapsed:m["execution_time"].append(float(elapsed))
        if failure and failure not in m["failure_patterns"]:m["failure_patterns"].append(failure)
        self._save(r);return r
    def find_similar(self,capabilities):
        need=set(capabilities);out=[]
        for p in self.dir.glob("*.json"):
            r=json.loads(p.read_text());have={s["capability"] for s in r["steps"]}
            if need & have:out.append(r)
        return out
