"""Explicit conversation access to persisted, authority-bounded skills."""
import json
from pathlib import Path
import re
from core.skill_registry import SkillRegistry, IMAGE_SEARCH_STEPS, is_builtin_image_search, IMAGE_CREATE_STEPS, is_builtin_image_create
from core.dynamic_skill_registry import DynamicSkillRegistry
from core.capability_registry import CapabilityRegistry
from core.capability_evolution import CapabilityEvolutionEngine
from core.skill_synthesizer import SkillSynthesizer

BASE_DIR = Path(__file__).resolve().parents[1]
_IMAGE_STEPS = IMAGE_SEARCH_STEPS


def skill_manager(parameters, **kwargs):
    params = parameters or {}
    store = SkillRegistry(BASE_DIR / 'storage/autonomy')
    dynamic = DynamicSkillRegistry(BASE_DIR / 'storage/autonomy', store)
    operation = params.get('operation', 'list')
    try:
        if operation == 'list':
            return json.dumps({'status':'SUCCESS', 'skills':[
                {k:r.get(k) for k in ('skill_id','name','purpose','skill_type','status','operational_state')}
                for r in store.all()]})
        if operation == 'ensure':
            from core.skill_fulfillment import fulfill
            def engine_factory():
                engine = CapabilityEvolutionEngine(store,dynamic,CapabilityRegistry(),SkillSynthesizer())
                engine.require_expected_tests = True
                return engine
            return fulfill(params,store,dynamic,BASE_DIR,engine_factory)
        if operation == 'create':
            name = str(params.get('name') or '')
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', name):
                raise ValueError('Use a lowercase snake_case skill name')
            if any(r.get('name') == name for r in store.all()):
                raise ValueError('Skill name already exists; list saved skills and use its ID')
            kind = params.get('kind')
            if kind in {'image_search','image_create'}:
                record = store.create(name, str(params.get('purpose') or ('Search for images' if kind=='image_search' else 'Create images')), _IMAGE_STEPS if kind=='image_search' else IMAGE_CREATE_STEPS,
                                      provenance={'template':'builtin_image_search_v1' if kind=='image_search' else 'builtin_image_create_v1'})
                return json.dumps({'status':'REGISTERED','skill_id':record['skill_id'],
                                   'verified':False,'instruction':'Saved built-in image composition only; no image has been created or searched yet. Run by ID with inputs.query for search or inputs.prompt for creation.'})
            if kind != 'pure':
                raise ValueError('Supported kinds: pure, image_search, image_create')
            engine = CapabilityEvolutionEngine(store, dynamic, CapabilityRegistry(), SkillSynthesizer())
            result = engine.ensure_capability(name, str(params.get('purpose') or ''), params.get('parameters'))
            record = result.get('skill') or {}
            return json.dumps({'status':result['status'], 'skill_id':record.get('skill_id'),
                               'reason':result.get('reason'), 'validation':result.get('validation'),
                               'instruction':'Only VERIFIED skills passed registration. No unrestricted network/filesystem skill was installed.'})
        if operation != 'run':
            raise ValueError('Supported operations: list, create, run')
        sid = str(params.get('skill_id') or '')
        if not re.fullmatch(r'[a-f0-9]{32}', sid):
            raise ValueError('Invalid skill ID; use list first')
        record = store.get(sid)
        if record.get('operational_state') not in {'ACTIVE','DEGRADED'}:
            raise ValueError('Skill is not active')
        inputs = params.get('inputs') or {}
        if not isinstance(inputs, dict):
            raise ValueError('Skill inputs must be an object')
        if (record.get('provenance') or {}).get('template') == 'approved_script_v1':
            from core.script_skills import run_script_skill
            return json.dumps(run_script_skill(record,BASE_DIR,inputs),ensure_ascii=False)
        if record.get('skill_type') == 'GENERATED':
            return json.dumps(dynamic.execute(sid, inputs), ensure_ascii=False)
        if is_builtin_image_create(record):
            from actions.image_create import image_create
            return image_create(inputs)
        if not is_builtin_image_search(record):
            raise ValueError('This composite requires the autonomy executor')
        from actions.web_search import web_search
        query = str(inputs.get('query') or '').strip()
        if not query:
            raise ValueError('A query is required')
        return web_search({'mode':'images','query':query, 'count':inputs.get('count', 6),
                           'delivery':inputs.get('delivery', 'attachments')})
    except Exception as exc:
        return json.dumps({'status':'FAILED','verified':False,'error_type':type(exc).__name__,
                           'instruction':'Skill operation failed; do not claim creation or execution succeeded. Inspect saved skills before retrying.'})


TOOL = {'name':'skill_manager',
    'description':'Create, list, run or ensure persisted reusable skills. operation=ensure reuses a matching saved skill or builds/tests/registers one, then immediately executes the original inputs. Requires name, kind, purpose and inputs. Use this when a missing capability is needed to fulfill the user request; do not stop at registration or ask the user to request a Mark code patch. kind=pure supports bounded pure Python; kind=script uses the existing approved code_helper build/run path with filesystem/network access and is NOT sandboxed. script is supported only by ensure, not create. Script builds already execute once; do not execute again after registration. A successful process still requires verification of the real requested output. Fixed image-search/image-create templates need no approval; generated Python retains host approval. kind=pure generates deterministic Python transformations through the existing Crucible checks; filesystem/network/process access is prohibited. kind=image_create saves the configured image-generation workflow; run with inputs.prompt. kind=image_search saves a composition of built-in web_search images. Saved skills are callable by ID after restart. List before run; do not invent IDs. Image runs produce reviewed generated images or download reviewed search results for companion Inbox handoff; internal execution alone does not prove delivery.',
    'parameters':{'type':'OBJECT','properties':{
        'operation':{'type':'STRING','enum':['list','create','run','ensure']},
        'kind':{'type':'STRING','enum':['pure','script','image_search','image_create']},
        'name':{'type':'STRING'},'purpose':{'type':'STRING'},
        'parameters':{'type':'OBJECT'}, 'skill_id':{'type':'STRING'},'inputs':{'type':'OBJECT'}},
        'required':['operation']},'handler':skill_manager}
