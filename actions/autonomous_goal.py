from __future__ import annotations
import json
from pathlib import Path
from core.autonomy_state import GoalStore,WorldState
from core.autonomy_engine import AutonomousCoordinator,Budget,state_verifier
from core.capability_registry import build_registry,Capability
from core.skill_registry import SkillRegistry
from core.composite_skill_runtime import CompositeSkillRuntime
from core.dynamic_skill_registry import DynamicSkillRegistry
from core.skill_synthesizer import SkillSynthesizer
from core.capability_evolution import CapabilityEvolutionEngine
from core.agent_memory import AgentMemory
from core.execution_trace import ExecutionTrace

BASE=Path(__file__).resolve().parents[1]
_AUTONOMY=BASE/"storage"/"autonomy"
_STORE=GoalStore(_AUTONOMY)
_WORLD=WorldState(_AUTONOMY)
_SKILLS=SkillRegistry(_AUTONOMY)
_MEMORY=AgentMemory(_AUTONOMY)
_DYNAMIC=DynamicSkillRegistry(_AUTONOMY,_SKILLS)
_TRACE=ExecutionTrace(_AUTONOMY)

# Bound once by main.py after the real server/device boundaries are available.
_DEVICES_PROVIDER=None
_SERVER_ACTIONS_PROVIDER=None
_DEVICE_EXECUTOR=None
_SERVER_EXECUTOR=None

def configure_runtime(*,devices_provider,server_actions_provider,device_executor,server_executor):
    global _DEVICES_PROVIDER,_SERVER_ACTIONS_PROVIDER,_DEVICE_EXECUTOR,_SERVER_EXECUTOR
    _DEVICES_PROVIDER=devices_provider;_SERVER_ACTIONS_PROVIDER=server_actions_provider
    _DEVICE_EXECUTOR=device_executor;_SERVER_EXECUTOR=server_executor

def _runtime_ready():
    return all(x is not None for x in (_DEVICES_PROVIDER,_SERVER_ACTIONS_PROVIDER,_DEVICE_EXECUTOR,_SERVER_EXECUTOR))

def _coordinator():
    if not _runtime_ready(): raise RuntimeError("autonomy_runtime_not_ready")
    devices=list(_DEVICES_PROVIDER() or [])
    server_actions=sorted(set(_SERVER_ACTIONS_PROVIDER() or ()))
    caps=build_registry(server_actions,devices)
    # Rehydrate persisted VERIFIED generated capabilities without importing their
    # source into the server process. DynamicSkillRegistry remains the executor.
    for decl in _DYNAMIC.declarations():
        sid=decl.get("skill_id"); rec=_SKILLS.get(sid)
        caps.register(Capability(name=decl["name"],purpose=decl.get("description") or rec.get("purpose",""),
                                 platform="server",device_id="server:evolved",permissions=(),risk="LOW",
                                 source="generated_skill",metadata={"skill_id":sid}))
    def execute(cap,args,goal):
        if getattr(cap,"source","")=="companion": return _DEVICE_EXECUTOR(cap,args,goal)
        return _SERVER_EXECUTOR(cap,args,goal)
    composite=CompositeSkillRuntime(caps,_SKILLS,execute)
    evolution=CapabilityEvolutionEngine(_SKILLS,_DYNAMIC,caps,SkillSynthesizer(),memory=_MEMORY)
    return AutonomousCoordinator(_STORE,_WORLD,caps,execute,state_verifier,Budget(),skills=_SKILLS,
                                 composite_runtime=composite,evolution_engine=evolution,tracer=_TRACE)

def autonomous_goal(parameters,**kwargs):
    parameters=parameters or {};op=str(parameters.get("operation","inspect")).lower()
    if op=="create":
        plan=parameters.get("plan") or []
        if plan:
            if not _runtime_ready():return json.dumps({"status":"FAILED","reason":"autonomy_runtime_not_ready"})
            budget_data=parameters.get("budget") or {}
            budget=Budget(**{k:v for k,v in budget_data.items() if k in Budget.__dataclass_fields__}) if isinstance(budget_data,dict) else Budget()
            goal=_coordinator().create_goal(parameters.get("objective",""),plan,parameters.get("origin_device",""),
                         parameters.get("origin_session",""),parameters.get("requested_target",""),parameters.get("granted_permissions") or (),budget)
        else:
            goal=_STORE.create(parameters.get("objective",""),parameters.get("origin_device",""),parameters.get("origin_session",""),parameters.get("requested_target",""))
        return json.dumps(goal,ensure_ascii=False)
    gid=str(parameters.get("goal_id",""))
    if op=="inspect":return json.dumps(_STORE.load(gid),ensure_ascii=False)
    if op=="resume":return json.dumps(_STORE.reconcile(gid),ensure_ascii=False)
    if op=="advance":
        if not _runtime_ready():return json.dumps({"status":"FAILED","reason":"autonomy_runtime_not_ready"})
        return json.dumps(_coordinator().advance(gid),ensure_ascii=False)
    if op=="observe":
        section=str(parameters.get("section",""));_WORLD.update_observed(section,parameters.get("value"),"autonomous_goal observation")
        return json.dumps({"status":"observed","section":section})
    return json.dumps({"status":"NO_SAFE_PROGRESS_POSSIBLE","reason":"unsupported_operation"})

TOOL={"name":"autonomous_goal","description":"Persist, inspect, reconcile, advance, or add independently observed world state for a long-running goal. Advance uses Mark's capability registry, risk/permission gates, verification, safe fallback, and skill lifecycle; it never bypasses companion pairing or repair approval boundaries.",
"parameters":{"type":"OBJECT","properties":{
    "operation":{"type":"STRING","enum":["create","inspect","resume","observe","advance"]},
    "objective":{"type":"STRING"},"goal_id":{"type":"STRING"},"origin_device":{"type":"STRING"},"origin_session":{"type":"STRING"},"requested_target":{"type":"STRING"},
    "granted_permissions":{"type":"ARRAY","items":{"type":"STRING"}},"budget":{"type":"OBJECT"},
    "plan":{"type":"ARRAY","items":{"type":"OBJECT"}},"section":{"type":"STRING"},"value":{}
},"required":["operation"]},"handler":autonomous_goal}
