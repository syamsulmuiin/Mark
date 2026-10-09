from core.verification_engine import GenericVerificationEngine
from core.capability_registry import CapabilityRegistry,Capability
from core.capability_gap import CapabilityGapResolver
from core.skill_registry import SkillRegistry
from core.autonomy_state import GoalStore,WorldState
from core.autonomy_engine import AutonomousCoordinator,Budget,state_verifier
from core.execution_trace import ExecutionTrace
from core.agent_memory import AgentMemory
from core.dynamic_skill_registry import DynamicSkillRegistry
from core.capability_evolution import CapabilityEvolutionEngine


def test_generic_verification_engine_changed_and_world_equals(tmp_path):
    v=GenericVerificationEngine()
    assert v.compare('a','b',{'op':'changed'}).verified is True
    w=WorldState(tmp_path);w.update_observed('app','open','process readback')
    out=v.verify_step({'capability':'app.inspect','verify':{'section':'app','equals':'open'}},{'status':'UNVERIFIED'},w,{})
    assert out['verified'] is True and out['evidence']['world_evidence']=='process readback'


def test_capability_registry_can_exclude_failed_device():
    r=CapabilityRegistry();r.register(Capability('inspect',device_id='a',permissions=('inspect',),success_count=9));r.register(Capability('inspect',device_id='b',permissions=('inspect',),success_count=8))
    assert r.select('inspect',granted_permissions=('inspect',)).device_id=='a'
    assert r.select('inspect',granted_permissions=('inspect',),exclude_device_ids=('a',)).device_id=='b'


def test_planner_v2_prefers_reliable_short_verified_composite(tmp_path):
    skills=SkillRegistry(tmp_path);caps=CapabilityRegistry()
    a=skills.create('short','x',[{'capability':'a'}],output_capability='derived');a=skills.promote(a['skill_id'],'CANDIDATE','s');a=skills.promote(a['skill_id'],'VERIFIED','v')
    b=skills.create('long','x',[{'capability':'a'},{'capability':'b'},{'capability':'c'}],output_capability='derived');b=skills.promote(b['skill_id'],'CANDIDATE','s');b=skills.promote(b['skill_id'],'VERIFIED','v')
    for _ in range(5):skills.record(a['skill_id'],True,.05)
    for _ in range(5):skills.record(b['skill_id'],True,1.0)
    out=CapabilityGapResolver(caps,skills).resolve('derived')
    assert out.skill_id==a['skill_id'] and out.evidence['planner']=='v2'


def test_safe_fallback_uses_second_executor_only_when_opted_in(tmp_path):
    store=GoalStore(tmp_path/'g');world=WorldState(tmp_path/'g');caps=CapabilityRegistry()
    caps.register(Capability('inspect',device_id='a',permissions=('inspect',),success_count=10));caps.register(Capability('inspect',device_id='b',permissions=('inspect',),success_count=5))
    calls=[]
    def ex(cap,args,g):
        calls.append(cap.device_id)
        return {'status':'FAILED','reason':'offline'} if cap.device_id=='a' else {'status':'SUCCESS','verified':True,'evidence':{'readback':'ok'}}
    c=AutonomousCoordinator(store,world,caps,ex,state_verifier,Budget())
    g=c.create_goal('inspect',[{'id':'1','capability':'inspect','fallback_safe':True,'verify':{'section':'x','equals':'ok'}}],granted_permissions=('inspect',))
    world.update_observed('x','ok','independent')
    out=c.advance(g['goal_id'])
    assert calls==['a','b'] and out['status']=='GOAL_ACHIEVED'


def test_fallback_is_not_used_without_explicit_safe_flag(tmp_path):
    store=GoalStore(tmp_path/'g');world=WorldState(tmp_path/'g');caps=CapabilityRegistry()
    caps.register(Capability('send',device_id='a',permissions=('send',),success_count=10));caps.register(Capability('send',device_id='b',permissions=('send',),success_count=5))
    calls=[]
    c=AutonomousCoordinator(store,world,caps,lambda cap,args,g:(calls.append(cap.device_id) or {'status':'FAILED','reason':'nope'}),state_verifier,Budget())
    g=c.create_goal('send',[{'id':'1','capability':'send','verify':{'section':'x','equals':'ok'}}],granted_permissions=('send',))
    c.advance(g['goal_id'])
    assert calls==['a']


def test_execution_trace_is_bounded_and_omits_inputs(tmp_path):
    t=ExecutionTrace(tmp_path,max_bytes=800);t.emit('execute',inputs={'token':'abc'},device='d')
    text=t.path.read_text();assert '[OMITTED]' in text and 'abc' not in text


class SeqSynth:
    def __init__(self):self.context_seen=None
    def synthesize(self,name,purpose='',parameters=None,context=None):
        self.context_seen=context
        return {'name':'calc','description':'calc','parameters':{'type':'OBJECT','properties':{}},'code':'def execute(**kwargs):\n    return 2\n','tests':[{'input':{},'expected':2}]}

def test_evolution_uses_verified_agent_memory_context(tmp_path):
    mem=AgentMemory(tmp_path/'mem');r=mem.add('failure','calc failed on old candidate','trace');mem.promote(r['id'],'VERIFIED','regression evidence')
    skills=SkillRegistry(tmp_path/'skills');caps=CapabilityRegistry();dyn=DynamicSkillRegistry(tmp_path/'dyn',skills);s=SeqSynth()
    evo=CapabilityEvolutionEngine(skills,dyn,caps,s,memory=mem);made=evo.ensure_capability('calc','calc')
    assert made['status']=='VERIFIED' and s.context_seen and 'calc failed' in s.context_seen[0]['statement']
    assert any(x['validation_status']=='VERIFIED' and 'passed Crucible' in x['statement'] for x in mem.search('calc'))

def test_autonomous_goal_runtime_is_wired_to_real_device_boundary():
    from pathlib import Path
    action=Path('actions/autonomous_goal.py').read_text(encoding='utf-8')
    main=Path('main.py').read_text(encoding='utf-8')
    dashboard=Path('dashboard/server.py').read_text(encoding='utf-8')
    assert 'op=="advance"' in action and 'AutonomousCoordinator' in action and 'CapabilityEvolutionEngine' in action
    assert '_autonomous_goal.configure_runtime' in main and 'self._dashboard.call_device' in main
    assert 'def autonomy_devices' in dashboard
    assert 'self_repair_apply' in main and 'capability_requires_dedicated_authority_path' in main
