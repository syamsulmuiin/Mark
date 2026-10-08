from core.action_result import normalize,SUCCESS,FAILED,UNVERIFIED
from core.capability_registry import CapabilityRegistry,Capability
from core.skill_registry import SkillRegistry
from core.capability_gap import CapabilityGapResolver
from core.composite_skill_runtime import CompositeSkillRuntime
from core.skill_crucible import SkillCrucible,SkillPolicyError
from core.dynamic_skill_registry import DynamicSkillRegistry
from core.capability_evolution import CapabilityEvolutionEngine
from core.autonomy_state import GoalStore,WorldState
from core.autonomy_engine import AutonomousCoordinator,Budget,state_verifier


def test_legacy_action_result_is_not_implicitly_verified():
    r=normalize({'ok':True,'result':'done'},capability='x')
    assert r['status']==UNVERIFIED and r['verified'] is False


def test_explicit_verified_result_survives_normalization():
    r=normalize({'status':'SUCCESS','verified':True,'result':7,'evidence':{'readback':7}},capability='x')
    assert r['status']==SUCCESS and r['verified'] is True


def test_gap_resolves_verified_composite(tmp_path):
    caps=CapabilityRegistry();skills=SkillRegistry(tmp_path)
    s=skills.create('combo','compose existing',[{'capability':'a'}],output_capability='missing')
    skills.promote(s['skill_id'],'CANDIDATE','static');skills.promote(s['skill_id'],'VERIFIED','functional')
    r=CapabilityGapResolver(caps,skills).resolve('missing')
    assert r.state=='COMPOSITE_AVAILABLE' and r.skill_id==s['skill_id']


def test_composite_requires_verified_steps(tmp_path):
    caps=CapabilityRegistry();caps.register(Capability('a',permissions=()))
    skills=SkillRegistry(tmp_path);s=skills.create('combo','x',[{'capability':'a'}],output_capability='missing')
    skills.promote(s['skill_id'],'CANDIDATE','static');skills.promote(s['skill_id'],'VERIFIED','functional')
    runtime=CompositeSkillRuntime(caps,skills,lambda cap,args,goal:{'status':'SUCCESS','verified':True,'result':'ok','evidence':{'probe':1}})
    out=runtime.execute(s['skill_id'],{},granted_permissions=())
    assert out['status']=='SUCCESS' and out['verified'] is True


def test_crucible_rejects_external_authority():
    for src in [
        'import os\ndef execute(**kwargs): return os.getcwd()',
        'def execute(**kwargs): return open("x").read()',
        'import socket\ndef execute(**kwargs): return 1',
        'def execute(**kwargs): return ().__class__.__base__.__subclasses__()',
    ]:
        try: SkillCrucible.validate_source(src)
        except SkillPolicyError: pass
        else: raise AssertionError(src)


def test_crucible_runs_pure_skill():
    src='def execute(**kwargs):\n    return int(kwargs.get("x",0))+1\n'
    out=SkillCrucible.run_tests(src,[{'input':{'x':2},'expected':3}])
    assert out['ok'] is True


def test_dynamic_registry_detects_tamper(tmp_path):
    skills=SkillRegistry(tmp_path);src='def execute(**kwargs):\n    return 4\n'
    validation=SkillCrucible.run_tests(src,[{'input':{},'expected':4}])
    r=skills.create('four','four',[],skill_type='GENERATED',output_capability='four')
    r=skills.promote(r['skill_id'],'CANDIDATE','static');r=skills.promote(r['skill_id'],'VERIFIED','tests')
    dyn=DynamicSkillRegistry(tmp_path,skills);dyn.install_verified(r,src,{'description':'four','parameters':{'type':'OBJECT','properties':{}}},validation)
    assert dyn.execute(r['skill_id'],{})['status']=='SUCCESS'
    (dyn._dir(r['skill_id'])/'skill.py').write_text('def execute(**kwargs): return 5')
    assert dyn.execute(r['skill_id'],{})['status']=='FAILED'
    assert skills.get(r['skill_id'])['operational_state']=='QUARANTINED'


def test_autonomy_uses_verified_composite_for_gap(tmp_path):
    store=GoalStore(tmp_path/'goal');world=WorldState(tmp_path/'goal');caps=CapabilityRegistry();skills=SkillRegistry(tmp_path/'skills')
    caps.register(Capability('base'))
    s=skills.create('combo','x',[{'capability':'base'}],output_capability='derived')
    skills.promote(s['skill_id'],'CANDIDATE','static');skills.promote(s['skill_id'],'VERIFIED','tests')
    runtime=CompositeSkillRuntime(caps,skills,lambda cap,args,goal:{'status':'SUCCESS','verified':True,'result':'ok','evidence':{'base':True}})
    c=AutonomousCoordinator(store,world,caps,lambda *a:None,state_verifier,Budget(),skills=skills,composite_runtime=runtime)
    g=c.create_goal('derive',[{'id':'1','capability':'derived','verify':{'section':'derived','equals':'ok'}}])
    world.update_observed('derived','ok','test')
    out=c.advance(g['goal_id'])
    assert out['status']=='GOAL_ACHIEVED'


class FakeSynth:
    def synthesize(self,name,purpose='',parameters=None):
        return {'name':'increment','description':'increment x','parameters':{'type':'OBJECT','properties':{'x':{'type':'INTEGER'}}},
                'code':'def execute(**kwargs):\n    return int(kwargs.get("x",0))+1\n',
                'tests':[{'input':{'x':1},'expected':2}]}


def test_evolution_creates_only_verified_pure_capability(tmp_path):
    skills=SkillRegistry(tmp_path);caps=CapabilityRegistry();dyn=DynamicSkillRegistry(tmp_path,skills)
    evo=CapabilityEvolutionEngine(skills,dyn,caps,FakeSynth())
    made=evo.ensure_capability('increment','increment')
    assert made['status']=='VERIFIED'
    cap=caps.select('increment')
    assert cap and cap.source=='generated_skill'
    assert evo.execute(cap,{'x':5})['result']==6


def test_device_mesh_records_capability_health(tmp_path):
    from core.device_mesh import DeviceMesh
    mesh=DeviceMesh(tmp_path)
    # Seed a trusted device directly for isolated persistence testing.
    mesh._trusted['d']={'device_id':'d','name':'D','public_key':'x','capabilities':['x'],'paired_at':0,'last_seen':0,'revoked':False}
    mesh._atomic(mesh.trust_path,mesh._trusted)
    mesh.set_capability_manifest('d',{'x':{'verification':'direct-evidence'},'unauthorized':{'x':1}})
    assert 'unauthorized' not in mesh.get('d')['capability_manifest']
    mesh.record_capability_result('d','x',False,100,'boom')
    mesh.record_capability_result('d','x',False,200,'boom')
    h=mesh.record_capability_result('d','x',False,300,'boom')
    assert h['failure_count']==3 and h['health']=='degraded'


def test_companions_emit_structured_capability_results_and_manifest():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    desktop=(root/'desktop-companion'/'companion.py').read_text(encoding='utf-8')
    android=(root/'android-companion'/'app'/'src'/'main'/'java'/'com'/'jarvis'/'companion'/'MainActivity.kt').read_text(encoding='utf-8')
    for text in (desktop,android):
        assert 'capability_manifest' in text
        assert 'verified' in text
        assert 'UNVERIFIED' in text

def test_unverified_execution_does_not_degrade_device_health(tmp_path):
    from core.device_mesh import DeviceMesh
    mesh=DeviceMesh(tmp_path)
    mesh._trusted['d']={'device_id':'d','capabilities':['x'],'revoked':False}
    for _ in range(4): mesh.record_capability_result('d','x',True,10,verified=False)
    h=mesh.get('d')['capability_health']['x']
    assert h['success_count']==4 and h['failure_count']==0
    assert h['unverified_count']==4 and h['verified_count']==0 and h['health']=='healthy'


def test_capability_routing_prefers_verified_healthy_executor():
    from core.capability_registry import CapabilityRegistry,Capability
    r=CapabilityRegistry()
    r.register(Capability(name='x',device_id='a',permissions=('x',),success_count=10,verified_count=0,unverified_count=10,avg_latency_ms=20))
    r.register(Capability(name='x',device_id='b',permissions=('x',),success_count=10,verified_count=10,unverified_count=0,avg_latency_ms=20))
    assert r.select('x',granted_permissions=('x',)).device_id=='b'


def test_quarantined_generated_skill_is_replaced_not_reactivated(tmp_path):
    from core.capability_evolution import CapabilityEvolutionEngine
    from core.capability_registry import CapabilityRegistry
    from core.skill_registry import SkillRegistry
    from core.dynamic_skill_registry import DynamicSkillRegistry
    class SeqSynth:
        def __init__(self): self.n=0
        def synthesize(self,*_a,**_k):
            self.n+=1
            if self.n==1:
                return {'name':'calc','description':'calc','parameters':{'type':'OBJECT','properties':{}},'code':'def execute(**kwargs):\n    if kwargs.get("fail"): raise ValueError("boom")\n    return 1','tests':[{'input':{},'expected':1}]}
            return {'name':'calc_v2','description':'calc','parameters':{'type':'OBJECT','properties':{}},'code':'def execute(**kwargs):\n    return 7','tests':[{'input':{},'expected':7}]}
    skills=SkillRegistry(tmp_path); caps=CapabilityRegistry(); dyn=DynamicSkillRegistry(tmp_path,skills); synth=SeqSynth()
    evo=CapabilityEvolutionEngine(skills,dyn,caps,synth)
    made=evo.ensure_capability('calc','calc'); cap=made['capability']; old=made['skill']['skill_id']
    # The candidate's declared error test lets it pass deterministic Crucible tests,
    # but repeated real invocation failures must quarantine it.
    for _ in range(4): evo.execute(cap,{'fail':True})
    out=evo.execute(cap,{'fail':True})
    assert out['status']=='SUCCESS' and out['result']==7
    assert out['recovery']['superseded']==old
    assert skills.get(old)['operational_state']=='RETIRED'
    assert cap.metadata['skill_id']!=old


def test_companion_sources_expose_observable_app_inspection_and_android_postconditions():
    from pathlib import Path
    desktop=Path('desktop-companion/companion.py').read_text(encoding='utf-8')
    android=Path('android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text(encoding='utf-8')
    service=Path('android-companion/app/src/main/java/com/jarvis/companion/JarvisAccessibilityService.kt').read_text(encoding='utf-8')
    assert "'app.inspect'" in desktop and '_inspect_app' in desktop
    assert '"app.inspect"' in android and 'activePackage()' in android
    assert 'snapshotFingerprint' in android and 'text_readback_match' in android
    assert 'fun snapshotFingerprint' in service and 'fun containsVisibleText' in service
