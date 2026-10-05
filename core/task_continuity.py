"""Persistent, application-agnostic continuity state for unfinished work."""
from __future__ import annotations
import json, os, threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "runtime"
STATE_FILE = STATE_DIR / "active_task.json"
_LOCK = threading.RLock()

def _now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _load():
    with _LOCK:
        try:
            data=json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data,dict) else {}
        except Exception:return {}
def _journal(kind, text, **meta):
    try:
        from memory.activity_journal import append
        append(kind, text, **meta)
    except Exception:
        pass

def _save(data):
    with _LOCK:
        STATE_DIR.mkdir(parents=True,exist_ok=True)
        tmp=STATE_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,STATE_FILE)

def active():
    d=_load(); return d if d.get('status') in {'IN_PROGRESS','WAITING','RECOVERING'} else {}
def begin(goal,constraints='',completion_criteria='',origin_device_id=''):
    current=active()
    if current and current.get('goal','').strip().casefold()==goal.strip().casefold(): return current
    d={'version':1,'status':'IN_PROGRESS','goal':goal.strip(),'constraints':constraints.strip(),
       'completion_criteria':completion_criteria.strip(),'origin_device_id':origin_device_id or '',
       'verified_checkpoints':[],'last_action':{},'blocker':'','created_at':_now(),'updated_at':_now()}
    _save(d); _journal('task_started', d['goal'], goal=d['goal']); return d
def checkpoint(summary,evidence=''):
    d=active()
    if not d:return {}
    summary=summary.strip(); evidence=evidence.strip()
    last=d.get('last_action') or {}
    # A checkpoint is verified continuity evidence only when it is anchored to
    # an observed, finished tool action. Free-form model claims are not enough.
    if not summary or not evidence or last.get('state')!='FINISHED':
        return {}
    item={'summary':summary,'evidence':evidence,'observed_action':dict(last),'at':_now()}
    d.setdefault('verified_checkpoints',[]).append(item)
    d['status']='IN_PROGRESS'; d['blocker']=''; d['updated_at']=_now(); _save(d); return d
def action_started(name,args):
    d=active()
    if not d or str(name)=='task_continuity':return
    d['last_action']={'name':str(name),'args':args,'state':'STARTED','at':_now()};d['updated_at']=_now();_save(d)
def action_finished(name,result):
    d=active()
    if not d or str(name)=='task_continuity':return
    d['last_action']={'name':str(name),'state':'FINISHED','result':str(result)[:4000],'at':_now()};d['updated_at']=_now();_save(d)
def block(reason):
    d=active()
    if not d:return {}
    d['status']='WAITING';d['blocker']=reason.strip();d['updated_at']=_now();_save(d);return d
def resume():
    d=active()
    if not d:return {}
    d['status']='RECOVERING';d['updated_at']=_now();_save(d);return d
def complete(evidence=''):
    d=active()
    if not d:return {}
    evidence=evidence.strip()
    checkpoints=d.get('verified_checkpoints') or []
    last=d.get('last_action') or {}
    latest=checkpoints[-1] if checkpoints else {}
    observed=latest.get('observed_action') or {}
    # Completion is a state transition, not a model assertion. Require explicit
    # evidence and a checkpoint tied to the latest real finished action. This
    # prevents an empty/claimed completion from turning unfinished work green.
    if (not evidence or last.get('state')!='FINISHED' or not latest.get('evidence')
            or observed.get('state')!='FINISHED'
            or observed.get('name')!=last.get('name')
            or observed.get('at')!=last.get('at')):
        return {}
    d['status']='COMPLETED';d['completion_evidence']=evidence;d['updated_at']=_now();_save(d)
    _journal('task_completed', d.get('goal',''), goal=d.get('goal',''), evidence=evidence, checkpoints=d.get('verified_checkpoints',[])[-6:])
    return d
def recovery_instruction():
    d=active()
    if not d:return ''
    last=d.get('last_action') or {}
    # A task that has only been begun is not an interrupted task.  Do not inject
    # it into a freshly reconnected conversation: doing so lets stale work take
    # precedence over the user's new request.  Automatic recovery is reserved
    # for an action that was actually in flight.
    if d.get('status') in {'IN_PROGRESS','RECOVERING'} and last.get('state') != 'STARTED':
        return ''
    cps=d.get('verified_checkpoints',[])[-12:]
    payload={'goal':d.get('goal',''),'constraints':d.get('constraints',''),
             'completion_criteria':d.get('completion_criteria',''),'status':d.get('status',''),
             'blocker':d.get('blocker',''),'verified_checkpoints':cps,'last_action':d.get('last_action',{}),
             'origin_device_id':d.get('origin_device_id','')}
    return ('[TASK_CONTINUITY_RECOVERY]\nAn unfinished persistent task exists. Continue it automatically; do not ask whether to continue. '
            'Treat checkpoints as claims to reconcile with the actual current state. Inspect/verify before relying on stale UI/device state, '
            'do not repeat already verified work unnecessarily, respect the credential boundary, and continue until the requested end state is verified.\n'
            + json.dumps(payload,ensure_ascii=False))
