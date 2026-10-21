"""Ensure a requested skill exists and execute its original inputs in one call."""
from __future__ import annotations

import json
import re
import threading
from core.skill_registry import is_builtin_image_search, is_builtin_image_create
from core.interaction_log import write_event

_LOCK=threading.RLock()


def fulfill(params,store,dynamic,base_dir,engine_factory):
    name=str(params.get('name') or '')
    kind=params.get('kind')
    purpose=str(params.get('purpose') or '').strip()
    inputs=params.get('inputs')
    if (not re.fullmatch(r'[a-z][a-z0-9_]{0,47}',name) or kind not in {'pure','script','image_search','image_create'}
            or not isinstance(inputs,dict) or len(json.dumps(inputs,ensure_ascii=False))>12000
            or len(purpose)>12000):
        raise ValueError('ensure requires valid name, kind, purpose and original inputs')
    def event(stage,**fields):
        write_event(base_dir/'runtime/interaction.log','skill_fulfillment',stage=stage,kind=kind,**fields)
    with _LOCK:
        matches=[r for r in store.all() if r.get('name')==name]
        if len(matches)>1:
            raise ValueError('Ambiguous saved skill name')
        record=matches[0] if matches else None
        schema=params.get('parameters') or {'type':'OBJECT','properties':{
            key:{'type':('BOOLEAN' if isinstance(value,bool) else 'NUMBER' if isinstance(value,(int,float))
                        else 'ARRAY' if isinstance(value,list) else 'OBJECT' if isinstance(value,dict) else 'STRING')}
            for key,value in inputs.items()}}
        if record:
            if purpose and (record.get('provenance') or {}).get('fulfillment_purpose',record.get('purpose'))!=purpose:
                raise ValueError('Saved skill purpose differs; do not overwrite it')
            if record.get('operational_state') not in {'ACTIVE','DEGRADED'}:
                raise ValueError('Saved skill is not active; do not silently replace it')
            valid=(kind=='pure' and record.get('skill_type')=='GENERATED'
                   and record.get('status') in {'VERIFIED','TRUSTED'}) or (
                       kind=='image_search' and is_builtin_image_search(record)) or (
                       kind=='image_create' and is_builtin_image_create(record)) or (
                       kind=='script' and (record.get('provenance') or {}).get('template')=='approved_script_v1')
            if not valid:
                raise ValueError('Saved skill kind does not match')
            event('reused',skill_id=record['skill_id'])
        else:
            if not purpose:
                raise ValueError('Purpose is required for a new skill')
            event('creating')
            if kind=='script':
                from core.script_skills import build_script_skill
                result=build_script_skill(store,base_dir,name,purpose,inputs)
                event('build_returned',status=result.get('status'),skill_id=result.get('skill_id'))
                return json.dumps(result,ensure_ascii=False)
            if kind=='pure':
                engine=engine_factory()
                made=None
                candidate_purpose=purpose
                for attempt in range(2):
                    try:
                        made=engine.ensure_capability(name,candidate_purpose,schema)
                    except Exception as exc:
                        made={'status':'REJECTED','reason':type(exc).__name__}
                    event('tested',attempt=attempt+1,status=made.get('status'),reason=made.get('reason'))
                    if made.get('status')=='VERIFIED':
                        break
                    if attempt==0:
                        # Repair only pure candidates; no external side effects have run.
                        candidate_purpose=purpose+'\nPrevious pure candidate failed validation: '+json.dumps({'reason':made.get('reason') or 'test_failure','validation':made.get('validation')},ensure_ascii=False)[:3000]
                if not made or made.get('status')!='VERIFIED':
                    return json.dumps({'status':'FAILED','verified':False,'reason':'skill_validation_failed',
                        'instruction':'Skill generation did not pass verification after two candidates. No original task execution occurred.'})
                record=made['skill']
                record['name']=name
                record['purpose']=purpose
                record.setdefault('provenance',{})['fulfillment_purpose']=purpose
                store._save(record)
            else:
                from core.skill_registry import IMAGE_SEARCH_STEPS,IMAGE_CREATE_STEPS
                record=store.create(name,purpose,IMAGE_SEARCH_STEPS if kind=='image_search' else IMAGE_CREATE_STEPS,
                    provenance={'template':'builtin_image_search_v1' if kind=='image_search' else 'builtin_image_create_v1'})
        sid=record['skill_id']
        event('executing',skill_id=sid)
        if kind=='pure':
            result=dynamic.execute(sid,inputs)
        elif kind=='script':
            from core.script_skills import run_script_skill
            result=run_script_skill(record,base_dir,inputs)
        elif kind=='image_search':
            from actions.web_search import web_search
            result=json.loads(web_search({**inputs,'mode':'images'}))
        else:
            from actions.image_create import image_create
            result=json.loads(image_create(inputs))
        result.update(skill_id=sid,skill_reused=bool(matches),
            fulfillment_stage='executed_original_inputs',
            fulfillment_instruction='Report the execution result, not merely registration. For files verify the actual artifact and deliver it; do not send source code instead. Do not repeat a successful execution merely to register the skill.')
        event('returned',skill_id=sid,status=result.get('status'))
        return json.dumps(result,ensure_ascii=False)
