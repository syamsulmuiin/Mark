import json
from pathlib import Path
import pytest
from core.autonomy_state import GoalStore,WorldState
from core.capability_registry import CapabilityRegistry,Capability
from core.agent_memory import AgentMemory
from core.skill_registry import SkillRegistry
from core.autonomy_engine import AutonomousCoordinator,Budget,state_verifier
from core.autonomy_health import HealthMonitor

def test_goal_persists_and_reconciles(tmp_path):
    s=GoalStore(tmp_path);g=s.create("x",origin_device="phone");g["status"]="RUNNING";s.save(g)
    r=s.reconcile(g["goal_id"]);assert r["status"]=="RECONCILING";assert r["origin_device"]=="phone"
def test_world_expected_observed_separate(tmp_path):
    w=WorldState(tmp_path);w.set_expected("service",{"health":"healthy"});w.update_observed("service",{"health":"failed"},"probe")
    assert w.data["expected"]["service"]!=w.observed("service")
def test_origin_and_permission_selection():
    r=CapabilityRegistry();r.register(Capability("app.open",device_id="laptop",platform="desktop",permissions=("app.open",),success_count=1))
    r.register(Capability("app.open",device_id="phone",platform="android",permissions=("app.open",),success_count=99))
    assert r.select("app.open",origin_device="laptop",granted_permissions=("app.open",)).device_id=="laptop"
    assert r.select("app.open",origin_device="laptop",granted_permissions=()) is None
def test_unavailable_not_selected():
    r=CapabilityRegistry();r.register(Capability("x",device_id="d",available=False));assert r.select("x") is None
def test_memory_requires_evidence_and_conflict_history(tmp_path):
    m=AgentMemory(tmp_path)
    with pytest.raises(ValueError):m.add("failure","x","")
    x=m.add("failure","bad route","trace");m.promote(x["id"],"VERIFIED","regression passed");c=m.contradiction(x["id"],"new source contradicts it")
    assert c["validation_status"]=="CANDIDATE";assert c["history"][-1]["status"]=="CONFLICT"
def test_skill_trust_requires_human(tmp_path):
    s=SkillRegistry(tmp_path);x=s.create("a","b",[{"capability":"x"}]);s.promote(x["skill_id"],"CANDIDATE","static/security tests");s.promote(x["skill_id"],"VERIFIED","functional regression")
    with pytest.raises(PermissionError):s.promote(x["skill_id"],"TRUSTED","ok")
    assert s.promote(x["skill_id"],"TRUSTED","human review",human_approved=True)["status"]=="TRUSTED"
def test_outcome_requires_independent_world_evidence(tmp_path):
    store=GoalStore(tmp_path);world=WorldState(tmp_path);reg=CapabilityRegistry();reg.register(Capability("app.open",device_id="laptop",permissions=("app.open",)))
    def ex(cap,args,g):return {"success":True,"claim":"opened"}
    c=AutonomousCoordinator(store,world,reg,ex,state_verifier,Budget(maximum_actions=3))
    g=c.create_goal("open",[{"id":"1","capability":"app.open","inputs":{},"verify":{"section":"chrome","equals":"open"}}],origin_device="laptop",granted_permissions=("app.open",))
    r=c.advance(g["goal_id"]);assert r["status"]=="RUNNING";assert r["completed_steps"]==[]
    world.update_observed("chrome","open","independent inspect");r=c.advance(g["goal_id"]);assert r["status"]=="GOAL_ACHIEVED"
def test_high_risk_stops_before_executor(tmp_path):
    called=[]
    store=GoalStore(tmp_path);world=WorldState(tmp_path);reg=CapabilityRegistry();reg.register(Capability("repair",risk="HIGH"))
    c=AutonomousCoordinator(store,world,reg,lambda *a:called.append(1),state_verifier,Budget(maximum_risk_level="HIGH"))
    g=c.create_goal("repair",[{"id":"1","capability":"repair","risk":"HIGH","verify":{"section":"x","equals":1}}])
    assert c.advance(g["goal_id"])["status"]=="HUMAN_APPROVAL_REQUIRED";assert not called
def test_action_budget_stops(tmp_path):
    store=GoalStore(tmp_path);world=WorldState(tmp_path);reg=CapabilityRegistry();reg.register(Capability("x"))
    c=AutonomousCoordinator(store,world,reg,lambda *a:1,state_verifier,Budget(maximum_actions=0))
    g=c.create_goal("x",[{"id":"1","capability":"x","verify":{"section":"x","equals":1}}]);assert c.advance(g["goal_id"])["status"]=="SAFETY_LIMIT_REACHED"
def test_health_unknown_has_no_recovery(tmp_path):
    w=WorldState(tmp_path);w.update_observed("server",{"health":"failed"},"probe");h=HealthMonitor(w)
    assert h.anomalies();assert h.recovery_candidate(h.anomalies()[0]) is None
