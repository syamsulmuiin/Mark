"""Hot registry for VERIFIED generated pure skills.

Generated source is never imported into the Mark server process. Each invocation
is re-validated and run by SkillCrucible's restricted runner.
"""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from core.skill_crucible import SkillCrucible
from core.action_result import make,SUCCESS,FAILED,BLOCKED

class DynamicSkillRegistry:
    def __init__(self,base_dir,skills):
        self.root=Path(base_dir)/"evolved_skills";self.root.mkdir(parents=True,exist_ok=True);self.skills=skills
    def _dir(self,sid):return self.root/str(sid)
    def install_verified(self,record,source,manifest,validation):
        if record.get('status') not in {'VERIFIED','TRUSTED'}:raise PermissionError('generated skill must be VERIFIED before runtime registration')
        if record.get('skill_type')!='GENERATED':raise ValueError('not a generated skill')
        policy=SkillCrucible.validate_source(source)
        if validation.get('ok') is not True:raise ValueError('validation evidence did not pass')
        d=self._dir(record['skill_id']);d.mkdir(parents=True,exist_ok=True)
        (d/'skill.py').write_text(source,encoding='utf-8')
        meta={"skill_id":record['skill_id'],"name":record['name'],"output_capability":record.get('output_capability') or record['name'],
              "manifest":manifest,"source_sha256":policy['sha256'],"policy":policy,"validation":validation}
        tmp=d/'manifest.tmp';tmp.write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8');os.replace(tmp,d/'manifest.json')
        return meta
    def get(self,sid):
        try:return json.loads((self._dir(sid)/'manifest.json').read_text(encoding='utf-8'))
        except Exception:return None
    def declarations(self):
        out=[]
        for p in self.root.glob('*/manifest.json'):
            try:
                m=json.loads(p.read_text(encoding='utf-8'));r=self.skills.get(m['skill_id'])
                if r.get('status') not in {'VERIFIED','TRUSTED'} or r.get('operational_state') not in {'ACTIVE','DEGRADED'}:continue
                schema=(m.get('manifest') or {}).get('parameters') or {"type":"OBJECT","properties":{}}
                out.append({"name":m['output_capability'],"description":(m.get('manifest') or {}).get('description') or r.get('purpose',''),"parameters":schema,"skill_id":m['skill_id']})
            except Exception:continue
        return out
    def execute(self,sid,args):
        rec=self.skills.get(sid)
        if rec.get('status') not in {'VERIFIED','TRUSTED'}:return make(BLOCKED,reason='skill_not_verified')
        if rec.get('operational_state') not in {'ACTIVE','DEGRADED'}:return make(BLOCKED,reason='skill_not_active')
        meta=self.get(sid)
        if not meta:return make(FAILED,reason='runtime_skill_missing')
        source=(self._dir(sid)/'skill.py').read_text(encoding='utf-8')
        digest=hashlib.sha256(source.encode()).hexdigest()
        if digest!=meta.get('source_sha256'):
            self.skills.set_operational_state(sid,'QUARANTINED','source hash mismatch')
            return make(FAILED,reason='skill_integrity_mismatch')
        result=SkillCrucible.run_once(source,args)
        ok=result.get('ok') is True
        self.skills.record(sid,ok,float((result.get('evidence') or {}).get('elapsed') or 0),failure='' if ok else result.get('reason','execution_failed'))
        if not ok:return make(FAILED,reason=result.get('reason','execution_failed'),evidence=result.get('evidence'))
        return make(SUCCESS,result.get('result'),verified=True,evidence=result.get('evidence'))
