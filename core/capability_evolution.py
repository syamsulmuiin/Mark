"""Authority-bounded capability evolution for low-risk pure generated skills."""
from __future__ import annotations
from core.capability_registry import Capability
from core.skill_crucible import SkillCrucible

class CapabilityEvolutionEngine:
    def __init__(self,skills,dynamic_registry,capabilities,synthesizer):
        self.skills=skills;self.dynamic=dynamic_registry;self.capabilities=capabilities;self.synthesizer=synthesizer

    def _create_verified(self,name,purpose,parameters,candidate,*,provenance=None):
        source=str(candidate['code']);tests=list(candidate.get('tests') or [{"input":{}}])
        validation=SkillCrucible.run_tests(source,tests)
        if not validation.get('ok'):
            return {"status":"REJECTED","reason":"crucible_failed","validation":validation}
        prov={"generator":"Mark SkillSynthesizer","policy":"pure-v1"}
        prov.update(provenance or {})
        record=self.skills.create(candidate.get('name') or name,candidate.get('description') or purpose,[],permissions=(),risk_level='LOW',
                                  output_capability=name,skill_type='GENERATED',provenance=prov)
        record=self.skills.promote(record['skill_id'],'CANDIDATE',{"static_policy":validation.get('policy')})
        record=self.skills.promote(record['skill_id'],'VERIFIED',{"tests":validation.get('results'),"elapsed":validation.get('elapsed')})
        meta=self.dynamic.install_verified(record,source,candidate,validation)
        cap=self.capabilities.register(Capability(name=name,purpose=candidate.get('description') or purpose,platform='server',device_id='server:evolved',permissions=(),risk='LOW',source='generated_skill',metadata={"skill_id":record['skill_id'],"source_sha256":meta['source_sha256']}))
        return {"status":"VERIFIED","capability":cap,"skill":record,"validation":validation}

    def ensure_capability(self,name,purpose='',parameters=None):
        existing=self.capabilities.select(name,granted_permissions=())
        if existing:return {"status":"EXISTS","capability":existing}
        candidate=self.synthesizer.synthesize(name,purpose,parameters)
        return self._create_verified(name,purpose,parameters,candidate)

    def recover_quarantined(self,cap,reason='runtime_failure'):
        """Create a fresh candidate; never edits/reactivates quarantined source in place."""
        sid=(cap.metadata or {}).get('skill_id')
        old=self.skills.get(sid)
        if old.get('operational_state')!='QUARANTINED':
            return {"status":"NOT_QUARANTINED"}
        candidate=self.synthesizer.synthesize(cap.name,cap.purpose,{"type":"OBJECT","properties":{}})
        made=self._create_verified(cap.name,cap.purpose,None,candidate,provenance={"supersedes":sid,"recovery_reason":str(reason)[:300]})
        if made.get('status')=='VERIFIED':
            self.skills.set_operational_state(sid,'RETIRED','superseded by verified recovery candidate')
            cap.metadata=dict(made['capability'].metadata)
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
