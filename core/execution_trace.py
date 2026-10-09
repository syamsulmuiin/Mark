"""Bounded, redacted lifecycle trace for autonomous execution decisions."""
from __future__ import annotations
import json, os, re
from datetime import datetime, timezone
from pathlib import Path

_SECRET = re.compile(r"(?i)(bearer\s+[^\s]+|(?:token|password|passwd|pin|otp|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+)")
def _now(): return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
def _clean(value):
    try: text=json.dumps(value,ensure_ascii=False,default=str)
    except Exception: text=str(value)
    text=_SECRET.sub("[REDACTED]",text)
    return text[:4000]

class ExecutionTrace:
    def __init__(self, base_dir, max_bytes=2_000_000):
        self.path=Path(base_dir)/"execution_trace.jsonl"; self.path.parent.mkdir(parents=True,exist_ok=True); self.max_bytes=int(max_bytes)
    def emit(self,event,**fields):
        rec={"at":_now(),"event":str(event)}
        for k,v in fields.items():
            if k in {"inputs","arguments","credentials"}: rec[k]="[OMITTED]"
            else:
                try: rec[k]=json.loads(_clean(v))
                except Exception: rec[k]=_clean(v)
        line=json.dumps(rec,ensure_ascii=False,separators=(",",":"))+"\n"
        if self.path.exists() and self.path.stat().st_size>self.max_bytes:
            data=self.path.read_bytes()[-self.max_bytes//2:]
            cut=data.find(b"\n")
            self.path.write_bytes(data[cut+1:] if cut>=0 else b"")
        with self.path.open("a",encoding="utf-8") as f: f.write(line)
        return rec
