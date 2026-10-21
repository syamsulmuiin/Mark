"""Explicit conversation access to persisted, authority-bounded skills."""
import json
from pathlib import Path
import re
from core.skill_registry import SkillRegistry
from core.dynamic_skill_registry import DynamicSkillRegistry
from core.capability_registry import CapabilityRegistry
from core.capability_evolution import CapabilityEvolutionEngine
from core.skill_synthesizer import SkillSynthesizer

BASE_DIR = Path(__file__).resolve().parents[1]
_IMAGE_STEPS = [{"capability": "web_search", "inputs": {"mode": "images"}}]


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
        if operation == 'create':
            name = str(params.get('name') or '')
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', name):
                raise ValueError('Use a lowercase snake_case skill name')
            if any(r.get('name') == name for r in store.all()):
                raise ValueError('Skill name already exists; list saved skills and use its ID')
            kind = params.get('kind')
            if kind == 'image_search':
                record = store.create(name, str(params.get('purpose') or 'Search for images'), _IMAGE_STEPS,
                                      provenance={'template':'builtin_image_search_v1'})
                return json.dumps({'status':'REGISTERED','skill_id':record['skill_id'],
                                   'verified':False,'instruction':'Saved search composition; no network search has run yet. Run this skill by ID with a query. Provider availability is required.'})
            if kind != 'pure':
                raise ValueError('Supported kinds: pure, image_search')
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
        if record.get('skill_type') == 'GENERATED':
            return json.dumps(dynamic.execute(sid, inputs), ensure_ascii=False)
        if record.get('steps') != _IMAGE_STEPS or record.get('provenance', {}).get('template') != 'builtin_image_search_v1':
            raise ValueError('This composite requires the autonomy executor')
        from actions.web_search import web_search
        query = str(inputs.get('query') or '').strip()
        if not query:
            raise ValueError('A query is required')
        return web_search({'mode':'images','query':query})
    except Exception as exc:
        return json.dumps({'status':'FAILED','verified':False,'error_type':type(exc).__name__,
                           'instruction':'Skill operation failed; do not claim creation or execution succeeded. Inspect saved skills before retrying.'})


TOOL = {'name':'skill_manager',
    'description':'Create, list, or run persisted reusable skills. Explicit creation uses host approval. kind=pure generates deterministic Python transformations through the existing Crucible checks; filesystem/network/process access is prohibited. kind=image_search saves a composition of built-in web_search images. Saved skills are callable by ID after restart. List before run; do not invent IDs. Search results are links, not downloaded attachments.',
    'parameters':{'type':'OBJECT','properties':{
        'operation':{'type':'STRING','enum':['list','create','run']},
        'kind':{'type':'STRING','enum':['pure','image_search']},
        'name':{'type':'STRING'},'purpose':{'type':'STRING'},
        'parameters':{'type':'OBJECT'}, 'skill_id':{'type':'STRING'},'inputs':{'type':'OBJECT'}},
        'required':['operation']},'handler':skill_manager}
