from __future__ import annotations
import json, os, uuid
from datetime import datetime,timezone
from pathlib import Path
def _now():return datetime.now(timezone.utc).isoformat(timespec="seconds")
class AgentMemory:
    TYPES={"semantic","episodic","procedural","failure","environment"}
    def __init__(self,base_dir):
        self.dir=Path(base_dir)/"knowledge"; self.dir.mkdir(parents=True,exist_ok=True)
    def add(self,kind,statement,evidence,confidence="CANDIDATE",environment=None,repository_commit="",related=None):
        if kind not in self.TYPES: raise ValueError("invalid memory type")
        if not str(evidence).strip(): raise ValueError("evidence required")
        rec={"id":uuid.uuid4().hex,"type":kind,"statement":str(statement),"evidence":str(evidence),"confidence":confidence,"validation_status":"CANDIDATE",
             "environment":environment or {},"repository_commit":repository_commit,"related_incidents":related or [],"created_at":_now(),"history":[]}
        self._write(rec); return rec
    def _write(self,r):
        p=self.dir/f"{r['id']}.json"; tmp=p.with_suffix(".tmp"); tmp.write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding="utf-8"); os.replace(tmp,p)
    def promote(self,mid,status,evidence):
        r=self.get(mid)
        if status not in {"VALIDATED","VERIFIED","REJECTED","EXPERIMENTAL","OBSOLETE","DEPRECATED"}:raise ValueError("invalid status")
        if not str(evidence).strip():raise ValueError("promotion evidence required")
        r.setdefault("history",[]).append({"status":r.get("validation_status"),"at":_now(),"evidence":evidence}); r["validation_status"]=status; r["evidence"]=str(evidence); self._write(r); return r
    def get(self,mid):
        return json.loads((self.dir/f"{mid}.json").read_text(encoding="utf-8"))
    def search(self,text,verified_only=False):
        words=set(str(text).lower().split()); out=[]
        for p in self.dir.glob("*.json"):
            try:r=json.loads(p.read_text(encoding="utf-8"))
            except Exception:continue
            if verified_only and r.get("validation_status")!="VERIFIED":continue
            score=len(words & set((r.get("statement","")+" "+r.get("evidence","")).lower().split()))
            if score:out.append((score,r))
        return [r for _,r in sorted(out,key=lambda x:x[0],reverse=True)]
    def contradiction(self,mid,new_evidence):
        r=self.get(mid); r.setdefault("history",[]).append({"status":"CONFLICT","at":_now(),"evidence":str(new_evidence)}); r["validation_status"]="CANDIDATE"; self._write(r); return r
