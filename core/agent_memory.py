from __future__ import annotations
import json, os, re, uuid
from datetime import datetime,timezone,timedelta
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
    def _path(self, mid):
        if not isinstance(mid, str) or not re.fullmatch(r'[0-9a-f]{32}', mid):
            raise ValueError('Invalid memory identifier')
        path = self.dir/f"{mid}.json"
        if path.is_symlink():raise ValueError('Memory must not be a symlink')
        return path
    def _write(self,r):
        p=self._path(r['id']); tmp=p.with_suffix(".tmp"); tmp.write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding="utf-8"); os.replace(tmp,p)
    def promote(self,mid,status,evidence):
        r=self.get(mid)
        if status not in {"VALIDATED","VERIFIED","REJECTED","EXPERIMENTAL","OBSOLETE","DEPRECATED"}:raise ValueError("invalid status")
        if not str(evidence).strip():raise ValueError("promotion evidence required")
        r.setdefault("history",[]).append({"status":r.get("validation_status"),"at":_now(),"evidence":evidence}); r["validation_status"]=status; r["validated_at"]=_now(); r["evidence"]=str(evidence); self._write(r); return r
    def get(self,mid):
        return json.loads(self._path(mid).read_text(encoding="utf-8"))
    def search(self,text,verified_only=False,*,environment=None,repository_commit=None,max_age_days=None,now=None,strict_scope=False):
        words=set(str(text).lower().split()); out=[]
        for p in self.dir.glob("*.json"):
            if p.is_symlink():continue
            try:r=json.loads(p.read_text(encoding="utf-8"))
            except Exception:continue
            if not isinstance(r, dict) or r.get("id") != p.stem:continue
            if verified_only and r.get("validation_status")!="VERIFIED":continue
            if environment is not None:
                scope = r.get('environment') or {}
                if not isinstance(scope, dict) or (strict_scope and not scope):continue
                if strict_scope and scope != environment:continue
                if any(environment.get(k) != v for k, v in scope.items()):continue
            if repository_commit is not None:
                if strict_scope and (not repository_commit or not r.get('repository_commit')):continue
                if r.get('repository_commit') and r['repository_commit'] != repository_commit:continue
            if max_age_days is not None:
                try:
                    at = datetime.fromisoformat(r.get('validated_at') or r['created_at'])
                    current = now or datetime.now(timezone.utc)
                    if at.tzinfo is None or at > current or current-at > timedelta(days=float(max_age_days)):continue
                except (ValueError, TypeError, KeyError):continue
            score=len(words & set((r.get("statement","")+" "+r.get("evidence","")).lower().split()))
            if score:out.append((score,r))
        return [r for _,r in sorted(out,key=lambda x:x[0],reverse=True)]
    def contradiction(self,mid,new_evidence):
        r=self.get(mid); r.setdefault("history",[]).append({"status":"CONFLICT","at":_now(),"evidence":str(new_evidence)}); r["validation_status"]="CANDIDATE"; self._write(r); return r
