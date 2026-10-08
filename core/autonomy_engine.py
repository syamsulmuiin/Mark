from __future__ import annotations
from dataclasses import dataclass
RANK={"LOW":0,"MEDIUM":1,"HIGH":2}
TERMINAL={"GOAL_ACHIEVED","SAFETY_LIMIT_REACHED","HUMAN_APPROVAL_REQUIRED","NO_SAFE_PROGRESS_POSSIBLE","FAILED"}
@dataclass
class Budget:
    maximum_actions:int=20; maximum_repair_attempts:int=3; maximum_external_calls:int=10; maximum_changed_files:int=10; maximum_risk_level:str="MEDIUM"
class AutonomousCoordinator:
    def __init__(self,store,world,capabilities,executor,verifier,budget=None,skills=None,composite_runtime=None,gap_resolver=None,evolution_engine=None):
        self.store=store;self.world=world;self.capabilities=capabilities;self.executor=executor;self.verifier=verifier;self.default_budget=budget or Budget()
        self.skills=skills; self.composite_runtime=composite_runtime; self.evolution_engine=evolution_engine
        if gap_resolver is None and skills is not None:
            from core.capability_gap import CapabilityGapResolver
            gap_resolver=CapabilityGapResolver(capabilities,skills)
        self.gap_resolver=gap_resolver
    def create_goal(self,objective,plan,origin_device="",origin_session="",requested_target="",granted_permissions=(),budget=None):
        d=self.store.create(objective,origin_device,origin_session,requested_target,budget=(budget or self.default_budget).__dict__)
        d["plan"]=plan;d["pending_steps"]=[x["id"] for x in plan];d["execution_context"]["granted_permissions"]=list(granted_permissions);d["status"]="RUNNING";return self.store.save(d)
    def advance(self,gid):
        g=self.store.reconcile(gid) or self.store.load(gid)
        if not g:return {"status":"FAILED","reason":"goal_not_found"}
        if g.get("status")=="RECONCILING":
            g["observations"].append({"type":"reconcile","observed_state":self.world.data.get("observed",{})});g["status"]="RUNNING";self.store.save(g)
        if g.get("status") in TERMINAL:return g
        budget=g.get("budget",{});max_actions=int(budget.get("maximum_actions",20));done=set(g.get("completed_steps",[]))
        if len(done)>=max_actions:g["status"]="SAFETY_LIMIT_REACHED";return self.store.save(g)
        pending=[s for s in g["plan"] if s["id"] not in done and all(x in done for x in s.get("depends_on",[]))]
        if not pending:g["status"]="GOAL_ACHIEVED" if len(done)==len(g["plan"]) else "NO_SAFE_PROGRESS_POSSIBLE";return self.store.save(g)
        s=pending[0];risk=s.get("risk","LOW").upper()
        if RANK.get(risk,2)>RANK.get(str(budget.get("maximum_risk_level","MEDIUM")).upper(),1) or risk=="HIGH":
            g["status"]="HUMAN_APPROVAL_REQUIRED";g["approvals"].append({"task_id":s["id"],"risk":risk,"status":"required"});return self.store.save(g)
        granted=g["execution_context"].get("granted_permissions",[])
        cap=self.capabilities.select(s["capability"],g.get("origin_device",""),g.get("requested_target",""),s.get("platform",""),granted)
        composite_id=""
        if not cap and self.gap_resolver is not None:
            resolution=self.gap_resolver.resolve(s["capability"],origin_device=g.get("origin_device",""),requested_target=g.get("requested_target",""),platform=s.get("platform",""),granted_permissions=granted,allow_evolution=bool(s.get("allow_evolution",False)))
            g["observations"].append({"task_id":s["id"],"type":"capability_gap","resolution":resolution.to_dict()})
            if resolution.state=="COMPOSITE_AVAILABLE" and self.composite_runtime is not None:
                composite_id=resolution.skill_id
            elif resolution.state=="EVOLUTION_ELIGIBLE":
                if self.evolution_engine is None:
                    g["status"]="NO_SAFE_PROGRESS_POSSIBLE"
                    g["failures"].append({"task_id":s["id"],"reason":"capability_evolution_required","capability":s["capability"]})
                    return self.store.save(g)
                evolved=self.evolution_engine.ensure_capability(s["capability"],s.get("purpose") or g.get("objective",""),s.get("parameters"))
                g["observations"].append({"task_id":s["id"],"type":"capability_evolution","status":evolved.get("status"),"validation":evolved.get("validation")})
                if evolved.get("status") not in {"VERIFIED","EXISTS"}:
                    g["status"]="NO_SAFE_PROGRESS_POSSIBLE";g["failures"].append({"task_id":s["id"],"reason":evolved.get("reason") or "capability_evolution_rejected"});return self.store.save(g)
                cap=evolved.get("capability")
        if not cap and not composite_id:
            g["status"]="NO_SAFE_PROGRESS_POSSIBLE";g["failures"].append({"task_id":s["id"],"reason":"capability_unavailable"});return self.store.save(g)
        g["execution_target"]=(f"skill:{composite_id}" if composite_id else cap.device_id);g["status"]="EXECUTING";self.store.save(g)
        if composite_id:
            result=self.composite_runtime.execute(composite_id,g,origin_device=g.get("origin_device",""),requested_target=g.get("requested_target",""),granted_permissions=granted)
        elif getattr(cap,"source","")=="generated_skill" and self.evolution_engine is not None:
            result=self.evolution_engine.execute(cap,s.get("inputs",{}))
        else:
            result=self.executor(cap,s.get("inputs",{}),g)
        g["observations"].append({"task_id":s["id"],"type":"executor_result","result":result})
        # Structured execution status can stop the loop before independent state
        # verification. Legacy executor results continue through the old path.
        structured_status=str(result.get("status","")).upper() if isinstance(result,dict) else ""
        if structured_status in {"FAILED","BLOCKED","WAITING"}:
            if cap:self.capabilities.record(cap.name,cap.device_id,False,error=result.get("reason",structured_status))
            g["failures"].append({"task_id":s["id"],"reason":result.get("reason") or structured_status.lower(),"evidence":result.get("evidence")})
            if structured_status in {"BLOCKED","WAITING"}:g["status"]="HUMAN_APPROVAL_REQUIRED" if structured_status=="BLOCKED" else "NO_SAFE_PROGRESS_POSSIBLE"
            else:
                s["attempts"]=int(s.get("attempts",0))+1
                g["status"]="RUNNING" if s["attempts"]<int(s.get("max_attempts",2)) else "NO_SAFE_PROGRESS_POSSIBLE"
            return self.store.save(g)
        g["status"]="VERIFYING";self.store.save(g)
        verdict=self.verifier(s,result,self.world,g)
        if verdict.get("verified") is True:
            g["completed_steps"].append(s["id"]);g["pending_steps"]=[x for x in g["pending_steps"] if x!=s["id"]]
            if cap:self.capabilities.record(cap.name,cap.device_id,True)
            g["status"]="GOAL_ACHIEVED" if len(g["completed_steps"])==len(g["plan"]) else "RUNNING"
        else:
            if cap:self.capabilities.record(cap.name,cap.device_id,False,error=verdict.get("reason","outcome_not_verified"))
            g["failures"].append({"task_id":s["id"],"reason":verdict.get("reason","outcome_not_verified"),"evidence":verdict.get("evidence")})
            s["attempts"]=int(s.get("attempts",0))+1
            g["status"]="RUNNING" if s["attempts"]<int(s.get("max_attempts",2)) else "NO_SAFE_PROGRESS_POSSIBLE"
        return self.store.save(g)
def state_verifier(step,result,world,goal):
    check=step.get("verify",{})
    if not check:return {"verified":False,"reason":"independent_verification_required"}
    section=check.get("section");expected=check.get("equals")
    actual=world.observed(section,None)
    return {"verified":actual==expected,"evidence":{"section":section,"expected":expected,"actual":actual},"reason":"" if actual==expected else "observed_state_mismatch"}
