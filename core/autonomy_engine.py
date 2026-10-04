from __future__ import annotations
from dataclasses import dataclass
RANK={"LOW":0,"MEDIUM":1,"HIGH":2}
TERMINAL={"GOAL_ACHIEVED","SAFETY_LIMIT_REACHED","HUMAN_APPROVAL_REQUIRED","NO_SAFE_PROGRESS_POSSIBLE","FAILED"}
@dataclass
class Budget:
    maximum_actions:int=20; maximum_repair_attempts:int=3; maximum_external_calls:int=10; maximum_changed_files:int=10; maximum_risk_level:str="MEDIUM"
class AutonomousCoordinator:
    def __init__(self,store,world,capabilities,executor,verifier,budget=None):
        self.store=store;self.world=world;self.capabilities=capabilities;self.executor=executor;self.verifier=verifier;self.default_budget=budget or Budget()
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
        cap=self.capabilities.select(s["capability"],g.get("origin_device",""),g.get("requested_target",""),s.get("platform",""),g["execution_context"].get("granted_permissions",[]))
        if not cap:g["status"]="NO_SAFE_PROGRESS_POSSIBLE";g["failures"].append({"task_id":s["id"],"reason":"capability_unavailable"});return self.store.save(g)
        g["execution_target"]=cap.device_id;g["status"]="EXECUTING";self.store.save(g)
        result=self.executor(cap,s.get("inputs",{}),g)
        g["observations"].append({"task_id":s["id"],"type":"executor_result","result":result})
        g["status"]="VERIFYING";self.store.save(g)
        verdict=self.verifier(s,result,self.world,g)
        if verdict.get("verified") is True:
            g["completed_steps"].append(s["id"]);g["pending_steps"]=[x for x in g["pending_steps"] if x!=s["id"]];self.capabilities.record(cap.name,cap.device_id,True)
            g["status"]="GOAL_ACHIEVED" if len(g["completed_steps"])==len(g["plan"]) else "RUNNING"
        else:
            self.capabilities.record(cap.name,cap.device_id,False);g["failures"].append({"task_id":s["id"],"reason":verdict.get("reason","outcome_not_verified"),"evidence":verdict.get("evidence")})
            s["attempts"]=int(s.get("attempts",0))+1
            g["status"]="RUNNING" if s["attempts"]<int(s.get("max_attempts",2)) else "NO_SAFE_PROGRESS_POSSIBLE"
        return self.store.save(g)
def state_verifier(step,result,world,goal):
    check=step.get("verify",{})
    if not check:return {"verified":False,"reason":"independent_verification_required"}
    section=check.get("section");expected=check.get("equals")
    actual=world.observed(section,None)
    return {"verified":actual==expected,"evidence":{"section":section,"expected":expected,"actual":actual},"reason":"" if actual==expected else "observed_state_mismatch"}
