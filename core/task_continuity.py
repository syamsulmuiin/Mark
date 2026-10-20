"""Persistent, application-agnostic continuity state for unfinished work."""
from __future__ import annotations
import json, os, tempfile, threading
from functools import wraps
import uuid
from core.action_outcomes import assess
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
            if (not isinstance(data, dict) or (data and (not isinstance(data.get("goal"), str)
                    or not isinstance(data.get("status"), str)
                    or not isinstance(data.get("last_action", {}), dict)
                    or not isinstance(data.get("verified_checkpoints", []), list)))):
                raise ValueError("Invalid task continuity state")
            return data
        except FileNotFoundError:return {}
def _journal(kind, text, **meta):
    try:
        from memory.activity_journal import append
        append(kind, text, **meta)
    except Exception:
        pass

def _save(data):
    with _LOCK:
        STATE_DIR.mkdir(parents=True,exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='active-task-', suffix='.tmp', dir=STATE_DIR)
        tmp = Path(name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, STATE_FILE)
        finally:
            tmp.unlink(missing_ok=True)

def _locked(fn):
    @wraps(fn)
    def invoke(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return invoke

def active():
    d=_load(); return d if d.get('status') in {'IN_PROGRESS','WAITING','RECOVERING'} else {}
@_locked
def begin(goal,constraints='',completion_criteria='',origin_device_id=''):
    current=active()
    if (current and current.get('origin_device_id', '') == (origin_device_id or '')
            and current.get('goal','').strip().casefold()==goal.strip().casefold()): return current
    d={'task_id':uuid.uuid4().hex,'version':1,'status':'IN_PROGRESS','goal':goal.strip(),'constraints':constraints.strip(),
       'completion_criteria':completion_criteria.strip(),'origin_device_id':origin_device_id or '',
       'verified_checkpoints':[],'last_action':{},'blocker':'','created_at':_now(),'updated_at':_now()}
    _save(d); _journal('task_started', d['goal'], goal=d['goal']); return d
@_locked
def checkpoint(summary,evidence=''):
    d=active()
    if not d:return {}
    summary=summary.strip(); evidence=evidence.strip()
    last=d.get('last_action') or {}
    # A checkpoint is verified continuity evidence only when it is anchored to
    # an observed, finished tool action. Free-form model claims are not enough.
    if not summary or not evidence or last.get('state')!='FINISHED' or last.get('outcome')!='VERIFIED':
        return {}
    if any((item.get('observed_action') or {}).get('id') == last.get('id')
           for item in d.get('verified_checkpoints', []) if last.get('id')):
        return d
    item={'summary':summary,'evidence':evidence,'observed_action':dict(last),'at':_now()}
    d.setdefault('verified_checkpoints',[]).append(item)
    d['status']='IN_PROGRESS'; d['blocker']=''; d['updated_at']=_now(); _save(d); return d
@_locked
def action_started(name,args):
    action_id = uuid.uuid4().hex
    d=active()
    if not d or str(name)=='task_continuity':return action_id
    d['last_action']={'name':str(name),'args':args,'state':'STARTED','id':action_id,'at':_now()};d['updated_at']=_now();_save(d)
    return action_id
@_locked
def action_finished(name,result,action_id=None):
    d=active()
    if not d or str(name)=='task_continuity':return
    last = d.get('last_action') or {}
    if action_id is not None and (last.get('id') != action_id or last.get('state') != 'STARTED' or last.get('name') != str(name)):
        return
    d['last_action']={'name':str(name),'state':'FINISHED','outcome':assess(result),'id':action_id or uuid.uuid4().hex,'result':str(result)[:4000],'at':_now()};d['updated_at']=_now();_save(d)
@_locked
def block(reason):
    d=active()
    if not d:return {}
    d['status']='WAITING';d['blocker']=reason.strip();d['updated_at']=_now();_save(d);return d
@_locked
def resume():
    d=active()
    if not d:return {}
    d['status']='RECOVERING';d['updated_at']=_now();_save(d);return d
@_locked
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
    if (not evidence or last.get('state')!='FINISHED' or last.get('outcome')!='VERIFIED' or not latest.get('evidence')
            or observed.get('state')!='FINISHED'
            or observed.get('name')!=last.get('name')
            or not last.get('id') or observed.get('id')!=last.get('id')):
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
            'An interrupted action may already have taken effect: never replay it or request its approval again solely because its result is missing. '
            'If the outcome cannot be inspected safely, preserve the task as blocked with an uncertain outcome. '
            'Do not repeat an already delivered final response. Do not treat recovery as fresh authorization. Respect the credential boundary, and continue until the requested end state is verified.\n'
            + json.dumps(payload,ensure_ascii=False))
