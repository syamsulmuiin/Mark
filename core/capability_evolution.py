"""Authority-bounded capability evolution for low-risk pure generated skills."""
from __future__ import annotations
from core.capability_registry import Capability
from core.skill_crucible import SkillCrucible
import inspect

class CapabilityEvolutionEngine:
    def __init__(self,skills,dynamic_registry,capabilities,synthesizer,memory=None):
        self.skills=skills;self.dynamic=dynamic_registry;self.capabilities=capabilities;self.synthesizer=synthesizer;self.memory=memory
    def _remember(self,kind,statement,evidence,environment=None,verified=False):
        if self.memory is None:return None
        try:
            rec=self.memory.add(kind,statement,str(evidence),environment=environment or {})
            if verified:rec=self.memory.promote(rec['id'],'VERIFIED',str(evidence))
            return rec
        except Exception:return None
    def _context(self,name):
        if self.memory is None:return []
        try:
            rows=self.memory.search(name,verified_only=True)[:6]
            return [{"type":r.get("type"),"statement":r.get("statement"),"evidence":str(r.get("evidence",""))[:600]} for r in rows]
        except Exception:return []
    def _synthesize(self,name,purpose,parameters):
        fn=self.synthesizer.synthesize
        if 'context' in inspect.signature(fn).parameters:
            return fn(name,purpose,parameters,context=self._context(name))
        return fn(name,purpose,parameters)

    def _create_verified(self,name,purpose,parameters,candidate,*,provenance=None):
        source=str(candidate['code']);tests=list(candidate.get('tests') or [{"input":{}}])
        validation=SkillCrucible.run_tests(source,tests)
        if not validation.get('ok'):
            self._remember("failure",f"Generated capability {name} failed Crucible",validation); return {"status":"REJECTED","reason":"crucible_failed","validation":validation}
        prov={"generator":"Mark SkillSynthesizer","policy":"pure-v1"}
        prov.update(provenance or {})
        record=self.skills.create(candidate.get('name') or name,candidate.get('description') or purpose,[],permissions=(),risk_level='LOW',
                                  output_capability=name,skill_type='GENERATED',provenance=prov)
        record=self.skills.promote(record['skill_id'],'CANDIDATE',{"static_policy":validation.get('policy')})
        record=self.skills.promote(record['skill_id'],'VERIFIED',{"tests":validation.get('results'),"elapsed":validation.get('elapsed')})
        meta=self.dynamic.install_verified(record,source,candidate,validation)
        cap=self.capabilities.register(Capability(name=name,purpose=candidate.get('description') or purpose,platform='server',device_id='server:evolved',permissions=(),risk='LOW',source='generated_skill',metadata={"skill_id":record['skill_id'],"source_sha256":meta['source_sha256']}))
        self._remember("procedural",f"Generated capability {name} passed Crucible and entered VERIFIED lifecycle",{"skill_id":record["skill_id"],"validation":validation},verified=True); return {"status":"VERIFIED","capability":cap,"skill":record,"validation":validation}

    def ensure_capability(self,name,purpose='',parameters=None):
        existing=self.capabilities.select(name,granted_permissions=())
        if existing:return {"status":"EXISTS","capability":existing}
        candidate=self._synthesize(name,purpose,parameters)
        return self._create_verified(name,purpose,parameters,candidate)

    def recover_quarantined(self,cap,reason='runtime_failure'):
        """Create a fresh candidate; never edits/reactivates quarantined source in place."""
        sid=(cap.metadata or {}).get('skill_id')
        old=self.skills.get(sid)
        if old.get('operational_state')!='QUARANTINED':
            return {"status":"NOT_QUARANTINED"}
        self._remember("failure",f"Generated capability {cap.name} was quarantined",{"skill_id":sid,"reason":reason}); candidate=self._synthesize(cap.name,cap.purpose,{"type":"OBJECT","properties":{}})
        made=self._create_verified(cap.name,cap.purpose,None,candidate,provenance={"supersedes":sid,"recovery_reason":str(reason)[:300]})
        if made.get('status')=='VERIFIED':
            self.skills.set_operational_state(sid,'RETIRED','superseded by verified recovery candidate')
            cap.metadata=dict(made['capability'].metadata)
            self._remember('procedural',f'Quarantined capability {cap.name} recovered through a fresh verified candidate',{'superseded':sid,'replacement':made['skill']['skill_id'],'reason':reason},verified=True)
        return made

    def execute(self,cap,args):
        sid=(cap.metadata or {}).get('skill_id')
        result=self.dynamic.execute(sid,args)
        # A pure LOW-risk generated skill that crossed the quarantine threshold may
        # be replaced once with a fresh candidate. The quarantined source is never
        # modified/reactivated; the replacement must pass the full Crucible again.
        if result.get('status')=='FAILED':
            try: current=self.skills.get(sid)
            except Exception: current={}
            if current.get('operational_state')=='QUARANTINED':
                recovered=self.recover_quarantined(cap,result.get('reason','runtime_failure'))
                if recovered.get('status')=='VERIFIED':
                    retry=self.dynamic.execute((cap.metadata or {}).get('skill_id'),args)
                    retry['recovery']={"status":"VERIFIED","superseded":sid,"skill_id":recovered['skill']['skill_id']}
                    return retry
                result['recovery']={"status":recovered.get('status'),"reason":recovered.get('reason','recovery_rejected')}
        return result
