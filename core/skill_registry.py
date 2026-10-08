from __future__ import annotations
import json,os,uuid
from datetime import datetime,timezone
from pathlib import Path

def _now():return datetime.now(timezone.utc).isoformat(timespec="seconds")

class SkillRegistry:
    """Persistent lifecycle/metrics store for declarative and generated skills.

    COMPOSITE skills remain the default and contain only existing capability
    references. GENERATED records describe candidate executable skills but are
    never considered executable until a separate verifier/registry promotes
    them to VERIFIED/TRUSTED.
    """
    def __init__(self,base_dir):
        self.dir=Path(base_dir)/"skills"; self.dir.mkdir(parents=True,exist_ok=True)

    def create(self,name,purpose,steps,permissions=(),risk_level="LOW",platforms=(),knowledge_reference=(),
               output_capability="",skill_type="COMPOSITE",provenance=None):
        skill_type=str(skill_type or "COMPOSITE").upper()
        if skill_type not in {"COMPOSITE","GENERATED"}:raise ValueError("invalid skill type")
        if skill_type=="COMPOSITE":
            if not steps:raise ValueError("skill requires steps")
            if any(not isinstance(s,dict) or not s.get("capability") for s in steps):raise ValueError("skills are declarative capability compositions")
        elif steps and any(not isinstance(s,dict) for s in steps):
            raise ValueError("generated skill metadata steps must be mappings")
        r={"skill_id":uuid.uuid4().hex,"name":name,"purpose":purpose,"steps":steps or [],"permissions":list(permissions),"risk_level":risk_level,
           "supported_platforms":list(platforms),"knowledge_reference":list(knowledge_reference),"status":"EXPERIMENTAL","operational_state":"DISABLED" if skill_type=="GENERATED" else "ACTIVE",
           "skill_type":skill_type,"output_capability":str(output_capability or name),"provenance":provenance or {},"history":[],
           "metrics":{"success_count":0,"failure_count":0,"rollback_count":0,"failure_patterns":[],"execution_time":[],"environments_tested":[],"last_validation":None,"known_limitations":[],"last_failure":None},"created_at":_now()}
        self._save(r);return r

    def _save(self,r):
        p=self.dir/f"{r['skill_id']}.json";t=p.with_suffix(".tmp");t.write_text(json.dumps(r,indent=2),encoding="utf-8");os.replace(t,p)
    def get(self,sid):return json.loads((self.dir/f"{sid}.json").read_text(encoding="utf-8"))
    def all(self):
        out=[]
        for p in sorted(self.dir.glob("*.json")):
            try: out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception: continue
        return out

    def promote(self,sid,target,validation,human_approved=False):
        r=self.get(sid); order={"EXPERIMENTAL":0,"CANDIDATE":1,"VERIFIED":2,"TRUSTED":3,"DEPRECATED":-1}
        target=str(target).upper()
        if target=="TRUSTED" and not human_approved:raise PermissionError("TRUSTED promotion requires human approval")
        if target not in order:raise ValueError("invalid status")
        if target!="DEPRECATED" and order[target]>order.get(r["status"],0)+1:raise ValueError("cannot skip lifecycle stage")
        if target in {"CANDIDATE","VERIFIED","TRUSTED"} and not validation:raise ValueError("validation evidence required")
        r["history"].append({"from":r["status"],"to":target,"at":_now(),"validation":validation});r["status"]=target;r["metrics"]["last_validation"]=_now()
        if target in {"VERIFIED","TRUSTED"} and r.get("operational_state")=="DISABLED":r["operational_state"]="ACTIVE"
        self._save(r);return r

    def set_operational_state(self,sid,state,reason=""):
        state=str(state).upper()
        if state not in {"ACTIVE","DEGRADED","QUARANTINED","DISABLED","RETIRED"}:raise ValueError("invalid operational state")
        r=self.get(sid); old=r.get("operational_state","ACTIVE")
        r["operational_state"]=state;r["history"].append({"operational_from":old,"operational_to":state,"at":_now(),"reason":reason})
        self._save(r);return r

    def record(self,sid,success,elapsed=0,failure="",environment=""):
        r=self.get(sid);m=r["metrics"];m["success_count" if success else "failure_count"]+=1
        if elapsed:m["execution_time"].append(float(elapsed))
        if failure:
            m["last_failure"]={"at":_now(),"reason":failure}
            if failure not in m["failure_patterns"]:m["failure_patterns"].append(failure)
        if environment and environment not in m["environments_tested"]:m["environments_tested"].append(environment)
        # Runtime health is separate from trust level. Repeated failure can
        # quarantine a skill but never silently demotes/promotes lifecycle trust.
        failures=int(m.get("failure_count",0)); successes=int(m.get("success_count",0))
        if failures>=3 and failures>successes and r.get("operational_state")=="ACTIVE":r["operational_state"]="DEGRADED"
        if failures>=5 and failures>=max(1,successes*2):r["operational_state"]="QUARANTINED"
        self._save(r);return r

    def find_similar(self,capabilities):
        need=set(capabilities);out=[]
        for r in self.all():
            have={s.get("capability") for s in r.get("steps",[]) if isinstance(s,dict)}
            if need & have:out.append(r)
        return out

    def find_for_capability(self,capability,executable_only=False):
        name=str(capability or "")
        out=[]
        for r in self.all():
            if str(r.get("output_capability") or r.get("name"))!=name:continue
            if executable_only:
                if r.get("status") not in {"VERIFIED","TRUSTED"}:continue
                if r.get("operational_state","ACTIVE") not in {"ACTIVE","DEGRADED"}:continue
            out.append(r)
        return out
