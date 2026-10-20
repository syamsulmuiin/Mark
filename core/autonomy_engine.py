from __future__ import annotations
from dataclasses import dataclass
import copy
import threading
from core.goal_contracts import validate_rule, requirement_coverage
from core.host_observations import artifact_reference

_ADVANCE_LOCK = threading.RLock()
RANK={"LOW":0,"MEDIUM":1,"HIGH":2}
TERMINAL={"INTERRUPTED","GOAL_ACHIEVED","SAFETY_LIMIT_REACHED","HUMAN_APPROVAL_REQUIRED","NO_SAFE_PROGRESS_POSSIBLE","FAILED"}
@dataclass
class Budget:
    maximum_actions:int=20; maximum_repair_attempts:int=3; maximum_external_calls:int=10; maximum_changed_files:int=10; maximum_risk_level:str="MEDIUM"
class AutonomousCoordinator:
    def __init__(self,store,world,capabilities,executor,verifier,budget=None,skills=None,composite_runtime=None,gap_resolver=None,evolution_engine=None,tracer=None,observer=None):
        self.store=store;self.world=world;self.capabilities=capabilities;self.executor=executor;self.verifier=verifier;self.default_budget=budget or Budget()
        self.observer=observer
        self.skills=skills; self.composite_runtime=composite_runtime; self.evolution_engine=evolution_engine; self.tracer=tracer
        if gap_resolver is None and skills is not None:
            from core.capability_gap import CapabilityGapResolver
            gap_resolver=CapabilityGapResolver(capabilities,skills)
        self.gap_resolver=gap_resolver
    def _trace(self,event,**fields):
        if self.tracer is not None:
            try:self.tracer.emit(event,**fields)
            except Exception:pass
    def create_goal(self,objective,plan,origin_device="",origin_session="",requested_target="",granted_permissions=(),budget=None,completion_checks=None,requirements=None):
        if not isinstance(plan, list) or not plan or any(not isinstance(s, dict) for s in plan):
            raise ValueError('nonempty_plan_required')
        ids = [s.get('id') for s in plan]
        if not plan or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('nonempty_unique_plan_steps_required')
        checks = completion_checks or []
        if not isinstance(checks, list) or any(not isinstance(c, dict) or not c.get('section') or (c.get('step_id') is not None and c['step_id'] not in ids) for c in checks):
            raise ValueError('invalid_completion_checks')
        for step in plan:
            if step.get('verify') is not None:validate_rule(step['verify'])
        for check in checks:validate_rule(check)
        required = requirements if requirements is not None else []
        coverage = requirement_coverage(required, checks)
        d=self.store.create(objective,origin_device,origin_session,requested_target,budget=(budget or self.default_budget).__dict__)
        d["requirements"]=required
        d["criteria_coverage"]=coverage
        d["completion_checks"]=checks
        d["plan"]=plan;d["pending_steps"]=[x["id"] for x in plan];d["execution_context"]["granted_permissions"]=list(granted_permissions);d["status"]="RUNNING";return self.store.save(d)
    def advance(self,gid):
        # Serialize read/execute/commit across coordinators in this process.
        with _ADVANCE_LOCK:
            return self._advance(gid)

    def _observe(self, step, result, g):
        if self.observer is None or not (step.get('verify') or {}).get('probe'):
            return True
        try:
            if self.observer(step, result, self.world, g) is True:
                return True
        except Exception as exc:
            self._trace("host_probe_failed", error_type=type(exc).__name__)
        # Do not allow an older observation to mask a failed fresh probe.
        section = (step.get('verify') or {}).get('section')
        self.world.update_observed(section, None, {'reason': 'host_probe_unavailable'})
        return False

    def _finish_goal(self, g):
        explicit = g.get('completion_checks', [])
        try:
            g['criteria_coverage'] = requirement_coverage(g.get('requirements', []), explicit)
        except ValueError:
            g['status'] = 'NO_SAFE_PROGRESS_POSSIBLE'
            g['completion_verification'] = [{'verified': False, 'reason': 'goal_requirements_not_covered'}]
            return self.store.save(g)
        checks = ([({'id': check.get('step_id', 'goal-final'), 'verify': check}, check) for check in explicit]
                  if explicit else [(step, step.get('verify') or {}) for step in g.get('plan', [])])
        decisions = []
        for step, check in checks:
            probe_ok = self._observe(step, None, g)
            verdict = self.verifier(step, {'status': 'UNVERIFIED'}, self.world, g) if probe_ok and check else {'verified': False, 'reason': 'goal_post_condition_unverified'}
            decisions.append({'step_id': step.get('id'), **verdict})
        g['completion_verification'] = decisions
        g['status'] = 'GOAL_ACHIEVED' if decisions and all(v.get('verified') is True for v in decisions) else 'NO_SAFE_PROGRESS_POSSIBLE'
        return self.store.save(g)

    def _recover_step(self, g):
        active = g['active_step']
        step = next((s for s in g.get('plan', []) if s.get('id') == active.get('id')), None)
        probe_ok = self._observe(step or {}, active.get('result'), g)
        observed = self.world.data.get('observed', {})
        reason = 'interrupted_step_requires_reinspection'
        verdict = None
        section = ((step or {}).get('verify') or {}).get('section')
        if probe_ok and section and observed.get(section) != active.get('observed_before', {}).get(section):
            result = active.get('result', {'status': 'UNVERIFIED', 'verified': False})
            verdict = self.verifier(step, result, self.world, g)
            if verdict.get('verified') is True:
                if step['id'] not in g['completed_steps']:
                    g['completed_steps'].append(step['id'])
                g['pending_steps'] = [x for x in g['pending_steps'] if x != step['id']]
                g.pop('active_step', None)
                g.pop('interrupted_status', None)
                g['status'] = 'GOAL_ACHIEVED' if len(g['completed_steps']) == len(g['plan']) else 'RUNNING'
                g['observations'].append({'type': 'recovery_verified', 'task_id': step['id'], 'evidence': verdict.get('evidence')})
                return self._finish_goal(g) if g['status'] == 'GOAL_ACHIEVED' else self.store.save(g)
            reason = 'interrupted_step_not_verified'
        g['status'] = 'NO_SAFE_PROGRESS_POSSIBLE'
        event = {'task_id': active.get('id'), 'reason': reason}
        if not g['failures'] or g['failures'][-1] != event:
            g['failures'].append(event)
        return self.store.save(g)

    def _advance(self,gid):
        g=self.store.load(gid)
        if g and g.get('status') not in TERMINAL and (g.get('status') in {'EXECUTING', 'VERIFYING'} or g.get('interrupted_status') in {'EXECUTING', 'VERIFYING'}) and not g.get('active_step'):
            g['status'] = 'NO_SAFE_PROGRESS_POSSIBLE'
            g['failures'].append({'reason': 'legacy_interrupted_step_requires_reinspection'})
            return self.store.save(g)
        g=self.store.reconcile(gid) or g
        if not g:return {"status":"FAILED","reason":"goal_not_found"}
        if g.get("status") == "INTERRUPTED":return g
        if g.get("active_step"):
            return self._recover_step(g)
        if g.get("status")=="RECONCILING":
            g["observations"].append({"type":"reconcile","observed_state":self.world.data.get("observed",{})});g["status"]="RUNNING";self.store.save(g)
        if g.get("status") == "NO_SAFE_PROGRESS_POSSIBLE" and g.get("plan") and len(g.get("completed_steps", [])) == len(g["plan"]):
            return self._finish_goal(g)
        if g.get("status") in TERMINAL:return g
        budget=g.get("budget",{});max_actions=int(budget.get("maximum_actions",20));done=set(g.get("completed_steps",[]))
        if len(done)>=max_actions:g["status"]="SAFETY_LIMIT_REACHED";return self.store.save(g)
        pending=[s for s in g["plan"] if s["id"] not in done and all(x in done for x in s.get("depends_on",[]))]
        if not pending:
            if g["plan"] and len(done)==len(g["plan"]):return self._finish_goal(g)
            g["status"]="NO_SAFE_PROGRESS_POSSIBLE";return self.store.save(g)
        s=pending[0];risk=s.get("risk","LOW").upper(); self._trace("step_selected",goal_id=gid,task_id=s.get("id"),capability=s.get("capability"),risk=risk)
        if RANK.get(risk,2)>RANK.get(str(budget.get("maximum_risk_level","MEDIUM")).upper(),1) or risk=="HIGH":
            g["status"]="HUMAN_APPROVAL_REQUIRED";g["approvals"].append({"task_id":s["id"],"risk":risk,"status":"required"});return self.store.save(g)
        granted=g["execution_context"].get("granted_permissions",[])
        cap=self.capabilities.select(s["capability"],g.get("origin_device",""),g.get("requested_target",""),s.get("platform",""),granted)
        if cap:self._trace("capability_selected",goal_id=gid,task_id=s.get("id"),capability=cap.name,device_id=cap.device_id,score=cap.score())
        composite_id=""
        if not cap and self.gap_resolver is not None:
            resolution=self.gap_resolver.resolve(s["capability"],origin_device=g.get("origin_device",""),requested_target=g.get("requested_target",""),platform=s.get("platform",""),granted_permissions=granted,allow_evolution=bool(s.get("allow_evolution",False)))
            g["observations"].append({"task_id":s["id"],"type":"capability_gap","resolution":resolution.to_dict()}); self._trace("capability_gap",goal_id=gid,task_id=s.get("id"),resolution=resolution.to_dict())
            if resolution.state=="COMPOSITE_AVAILABLE" and self.composite_runtime is not None:
                composite_id=resolution.skill_id
            elif resolution.state=="EVOLUTION_ELIGIBLE":
                if self.evolution_engine is None:
                    g["status"]="NO_SAFE_PROGRESS_POSSIBLE"
                    g["failures"].append({"task_id":s["id"],"reason":"capability_evolution_required","capability":s["capability"]})
                    return self.store.save(g)
                evolved=self.evolution_engine.ensure_capability(s["capability"],s.get("purpose") or g.get("objective",""),s.get("parameters")); self._trace("capability_evolution",goal_id=gid,task_id=s.get("id"),status=evolved.get("status"),reason=evolved.get("reason",""))
                g["observations"].append({"task_id":s["id"],"type":"capability_evolution","status":evolved.get("status"),"validation":evolved.get("validation")})
                if evolved.get("status") not in {"VERIFIED","EXISTS"}:
                    g["status"]="NO_SAFE_PROGRESS_POSSIBLE";g["failures"].append({"task_id":s["id"],"reason":evolved.get("reason") or "capability_evolution_rejected"});return self.store.save(g)
                cap=evolved.get("capability")
        if not cap and not composite_id:
            g["status"]="NO_SAFE_PROGRESS_POSSIBLE";g["failures"].append({"task_id":s["id"],"reason":"capability_unavailable"});return self.store.save(g)
        g["execution_target"]=(f"skill:{composite_id}" if composite_id else cap.device_id);g["status"]="EXECUTING"
        g["active_step"]={"id":s["id"],"execution_target":g["execution_target"],"observed_before":copy.deepcopy(self.world.data.get("observed",{}))}
        g["execution_context"].setdefault("step_targets", {})[s["id"]] = g["execution_target"]
        check = s.get('verify') or {}
        section = check.get('before_section') or check.get('section')
        if section:
            g['execution_context'].setdefault('verification_baselines', {})[s['id']] = {
                section: copy.deepcopy(self.world.observed(section))}
        self.store.save(g)
        if composite_id:
            result=self.composite_runtime.execute(composite_id,g,origin_device=g.get("origin_device",""),requested_target=g.get("requested_target",""),granted_permissions=granted)
        elif getattr(cap,"source","")=="generated_skill" and self.evolution_engine is not None:
            result=self.evolution_engine.execute(cap,s.get("inputs",{}))
        else:
            result=self.executor(cap,s.get("inputs",{}),g)
        g["active_step"]["result"] = result
        reference = artifact_reference(result)
        if reference:g["execution_context"].setdefault("step_artifacts", {})[s["id"]] = reference
        self.store.save(g)
        g["observations"].append({"task_id":s["id"],"type":"executor_result","result":result}); self._trace("execution_result",goal_id=gid,task_id=s.get("id"),capability=s.get("capability"),device_id=(cap.device_id if cap else g.get("execution_target")),status=(result.get("status") if isinstance(result,dict) else "LEGACY"),verified=(result.get("verified") if isinstance(result,dict) else False))
        # Structured execution status can stop the loop before independent state
        # verification. Legacy executor results continue through the old path.
        structured_status=str(result.get("status","")).upper() if isinstance(result,dict) else ""
        # Safe fallback is opt-in. It is only attempted after FAILED (never
        # WAITING/BLOCKED) and only when the planner marked this operation as
        # safe to repeat on another executor/device.
        if structured_status=="FAILED" and cap is not None and bool(s.get("fallback_safe",False)) and not s.get("fallback_attempted"):
            alt=self.capabilities.select(s["capability"],g.get("origin_device",""),g.get("requested_target",""),s.get("platform",""),granted,exclude_device_ids=(cap.device_id,))
            s["fallback_attempted"]=True
            if alt is not None:
                self._trace("fallback_selected",goal_id=gid,task_id=s.get("id"),from_device=cap.device_id,to_device=alt.device_id,capability=alt.name)
                g["active_step"]["execution_target"] = alt.device_id
                g["active_step"].pop("result", None)
                self.store.save(g)
                alt_result=self.executor(alt,s.get("inputs",{}),g)
                g["active_step"]["result"] = alt_result
                reference = artifact_reference(alt_result)
                if reference:g["execution_context"].setdefault("step_artifacts", {})[s["id"]] = reference
                self.store.save(g)
                g["observations"].append({"task_id":s["id"],"type":"fallback_executor_result","device_id":alt.device_id,"result":alt_result})
                self.capabilities.record(cap.name,cap.device_id,False,error=result.get("reason","execution_failed"))
                cap=alt; result=alt_result
                structured_status=str(result.get("status","")).upper() if isinstance(result,dict) else ""
                self._trace("fallback_result",goal_id=gid,task_id=s.get("id"),device_id=alt.device_id,status=structured_status or "LEGACY")
        if structured_status in {"FAILED","BLOCKED","WAITING"}:
            if structured_status == "FAILED" and s.get("fallback_safe", False):
                g.pop("active_step", None)
            if cap:self.capabilities.record(cap.name,cap.device_id,False,error=result.get("reason",structured_status))
            g["failures"].append({"task_id":s["id"],"reason":result.get("reason") or structured_status.lower(),"evidence":result.get("evidence")})
            if structured_status in {"BLOCKED","WAITING"}:g["status"]="HUMAN_APPROVAL_REQUIRED" if structured_status=="BLOCKED" else "NO_SAFE_PROGRESS_POSSIBLE"
            else:
                s["attempts"]=int(s.get("attempts",0))+1
                g["status"]="RUNNING" if s.get("fallback_safe", False) and s["attempts"]<int(s.get("max_attempts",2)) else "NO_SAFE_PROGRESS_POSSIBLE"
            return self.store.save(g)
        g["status"]="VERIFYING";self.store.save(g)
        probe_ok = self._observe(s, result, g)
        verdict=self.verifier(s,result,self.world,g) if probe_ok else {"verified":False,"reason":"host_probe_unavailable"}; self._trace("verification_result",goal_id=gid,task_id=s.get("id"),verified=verdict.get("verified"),reason=verdict.get("reason",""),evidence=verdict.get("evidence"))
        if verdict.get("verified") is True:
            g.pop("active_step", None)
            g["completed_steps"].append(s["id"]);g["pending_steps"]=[x for x in g["pending_steps"] if x!=s["id"]]
            if cap:self.capabilities.record(cap.name,cap.device_id,True)
            g["status"]="GOAL_ACHIEVED" if len(g["completed_steps"])==len(g["plan"]) else "RUNNING"
        else:
            if s.get("fallback_safe", False):
                g.pop("active_step", None)
            if cap:self.capabilities.record(cap.name,cap.device_id,False,error=verdict.get("reason","outcome_not_verified"))
            g["failures"].append({"task_id":s["id"],"reason":verdict.get("reason","outcome_not_verified"),"evidence":verdict.get("evidence")})
            s["attempts"]=int(s.get("attempts",0))+1
            g["status"]="RUNNING" if s.get("fallback_safe", False) and s["attempts"]<int(s.get("max_attempts",2)) else "NO_SAFE_PROGRESS_POSSIBLE"
        return self._finish_goal(g) if g["status"] == "GOAL_ACHIEVED" else self.store.save(g)
def state_verifier(step,result,world,goal):
    from core.verification_engine import verify_step
    return verify_step(step,result,world,goal)


# The service owns this supervisor; reasoning/execution lives in its child.
def _owned_worker(data):
    import os
    import math
    import psutil
    pid = data.get('pid')
    if type(pid) is not int or pid <= 1 or pid in {os.getpid(), data.get('owner_pid')}:
        return None
    try:
        process = psutil.Process(pid)
        created=float(data['create_time'])
        if not math.isfinite(created) or abs(process.create_time()-created) > .01:return None
        command = process.cmdline()
        if ('core.agent_worker' not in command or '--run-id' not in command
                or command[command.index('--run-id')+1] != data['run_id']):return None
        return process
    except (psutil.Error, KeyError, ValueError, IndexError, TypeError):
        return None


def emergency_break(base_dir=None):
    """Kill only the identity-checked worker, never the server/companion PID."""
    import os
    import signal
    import psutil
    from core.autonomy_state import AgentRuntimeState
    state = AgentRuntimeState(base_dir)
    with state.locked():
        data = state.read()
        if data.get('status') == 'idle':return {'status':'idle','stopped':False,'reason':'no_agent_worker'}
        if data.get('status') != 'running' or type(data.get('pid')) is not int or data['pid'] <= 1:
            return {'status':'FAILED','stopped':False,'reason':'invalid_worker_metadata'}
        process = _owned_worker(data)
        if process is None:
            if data.get('pid') and psutil.pid_exists(data['pid']):
                return {'status':'FAILED','stopped':False,'reason':'worker_identity_mismatch'}
        else:
            # Kill immediately; graceful cancellation is not an emergency stop.
            try:
                descendants = process.children(recursive=True)
                if os.name != 'nt' and os.getpgid(process.pid) == process.pid:
                    os.killpg(process.pid, signal.SIGKILL)
                else:process.kill()
                for child in reversed(descendants):
                    try:child.kill()
                    except psutil.NoSuchProcess:pass
                try:process.wait(timeout=1)
                except psutil.TimeoutExpired:
                    if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:raise
            except psutil.NoSuchProcess:pass
            except (psutil.Error, OSError):
                return {'status':'FAILED','stopped':False,'reason':'worker_kill_not_confirmed'}
        # Never erase STARTED steps: remote side effects may already have occurred.
        goal_error = ''
        try:state.interrupt_goal(data)
        except Exception as exc:goal_error=type(exc).__name__
        data.update(status='idle', pid=None, reason='emergency_stop', recovery_error=goal_error)
        state.write(data)
        return {'status':'idle','stopped':process is not None,'reason':'emergency_stop',
                'goal_recovery_error':goal_error}


class AgentProcessManager:
    """One supervised worker per server root; no automatic restart after stop."""
    def __init__(self, base_dir=None):
        from core.autonomy_state import AgentRuntimeState
        self.state = AgentRuntimeState(base_dir)

    @property
    def pid(self):
        return self.state.read().get('pid')

    def stop(self):
        return emergency_break(self.state.base)

    def run(self, entrypoint, payload, *, device_rpc=None, goal_id=''):
        import json
        import os
        import subprocess
        import sys
        import uuid
        import psutil
        run_id = uuid.uuid4().hex
        process = None
        with self.state.locked():
            current = self.state.read()
            if current.get('status') == 'running':
                if _owned_worker(current) is not None:
                    return {'status':'WAITING','reason':'agent_worker_busy','verified':False}
                if current.get('pid') and psutil.pid_exists(current['pid']):
                    return {'status':'FAILED','reason':'worker_identity_mismatch','verified':False}
            flags = {'start_new_session':True} if os.name != 'nt' else {
                'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
            log_path = self.state.path.parent/'agent_worker.log'
            with os.fdopen(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'ab') as log:
                process = subprocess.Popen([sys.executable,'-m','core.agent_worker','--run-id',run_id],
                    cwd=self.state.base, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                    text=True, encoding='utf-8', bufsize=1, **flags)
            try:
                created = psutil.Process(process.pid).create_time()
            except psutil.Error:
                process.kill();process.wait(timeout=3)
                process.stdin.close();process.stdout.close()
                return {'status':'FAILED','reason':'worker_identity_unavailable','verified':False}
            data = {'status':'running','pid':process.pid,'create_time':created,
                    'owner_pid':os.getpid(),'run_id':run_id,'goal_id':goal_id}
            try:self.state.write(data)
            except Exception:
                process.kill();process.wait(timeout=3);raise
        reason = 'worker_exited'
        try:
            process.stdin.write(json.dumps({'entrypoint':entrypoint,'payload':payload})+'\n');process.stdin.flush()
            while True:
                line = process.stdout.readline(8*1024*1024+1)
                if not line:break
                if len(line)>8*1024*1024:raise ValueError('worker_message_limit')
                message = json.loads(line)
                if message.get('type') == 'device_call':
                    if device_rpc is None:reply={'status':'FAILED','reason':'device_bridge_unavailable'}
                    else:
                        reply=device_rpc(message['capability'],message.get('args') or {},message.get('goal') or {})
                    if process.poll() is None:
                        process.stdin.write(json.dumps({'result':reply})+'\n');process.stdin.flush()
                elif message.get('type') == 'result':
                    reason='completed'
                    return message['result']
                elif message.get('type') == 'error':
                    reason='worker_failed'
                    return {'status':'FAILED','reason':'agent_worker_failed','error_type':message.get('error_type'),'verified':False}
            return {'status':'CANCELLED','reason':'agent_worker_interrupted','verified':False}
        except (OSError, ValueError):
            return {'status':'CANCELLED','reason':'agent_worker_interrupted','verified':False}
        finally:
            if process.poll() is None:
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:self.stop()
            # EOF/crash keeps goal evidence and stops accidental replay.
            if reason != 'completed':
                try:self.state.interrupt_goal(data)
                except Exception:pass
            if process.poll() is not None:
                self.state.finish(run_id, reason)
            process.stdin.close();process.stdout.close()
