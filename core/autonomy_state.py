from __future__ import annotations
import json, os, re, tempfile, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DIR=ROOT/"storage"/"autonomy"
_LOCK=threading.RLock()
def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _read(path,default):
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):raise ValueError("Invalid autonomy state")
        return data
    except FileNotFoundError:return default
def _atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.stem+'-', suffix='.tmp', dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

class GoalStore:
    def __init__(self,base_dir=None): self.dir=Path(base_dir or DEFAULT_DIR)/"goals"; self.dir.mkdir(parents=True,exist_ok=True)
    def create(self,objective,origin_device="",origin_session="",requested_target="",constraints=None,budget=None):
        gid=uuid.uuid4().hex
        d={"goal_id":gid,"objective":str(objective).strip(),"status":"PLANNING","origin_device":origin_device or "","origin_session":origin_session or "",
           "requested_target":requested_target or "","execution_target":"","constraints":constraints or {},"budget":budget or {},
           "plan":[],"completed_steps":[],"pending_steps":[],"observations":[],"artifacts":[],"approvals":[],"failures":[],
           "rollback_point":None,"knowledge_used":[],"execution_context":{},"created_at":now(),"updated_at":now()}
        self.save(d); return d
    def path(self,gid):
        if not isinstance(gid, str) or not re.fullmatch(r'[0-9a-f]{32}', gid):
            raise ValueError('Invalid goal identifier')
        path = self.dir/f"{gid}.json"
        if path.is_symlink():raise ValueError('Goal state must not be a symlink')
        return path
    def save(self,d):
        d=dict(d); d["updated_at"]=now()
        with _LOCK:_atomic(self.path(d["goal_id"]),d)
        return d
    def load(self,gid): return _read(self.path(gid),{})
    def list_active(self):
        return [d for p in self.dir.glob("*.json") if (d:=_read(p,{})).get("status") not in {"GOAL_ACHIEVED","CANCELLED","FAILED"}]
    def reconcile(self,gid):
        d=self.load(gid)
        if d and d.get("status") in {"RUNNING","EXECUTING","VERIFYING"}:
            d["interrupted_status"]=d["status"];d["status"]="RECONCILING"; d.setdefault("observations",[]).append({"at":now(),"type":"resume","claim":"state_requires_reinspection"}); self.save(d)
        return d
class WorldState:
    def __init__(self,base_dir=None):
        self.path=Path(base_dir or DEFAULT_DIR)/"world_state.json"
        self.data=_read(self.path,{"expected":{},"observed":{},"updated_at":None})
    def update_observed(self,section,value,evidence=""):
        self.data.setdefault("observed",{})[section]={"value":value,"evidence":evidence,"at":now(),"observation_id":uuid.uuid4().hex,"source":"host"}; self.data["updated_at"]=now(); _atomic(self.path,self.data); return self.data
    def set_expected(self,section,value):
        self.data.setdefault("expected",{})[section]=value; self.data["updated_at"]=now(); _atomic(self.path,self.data); return self.data
    def observed(self,section,default=None): return (self.data.get("observed",{}).get(section) or {}).get("value",default)
