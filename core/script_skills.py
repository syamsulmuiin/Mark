"""Reusable script workflows behind the existing host confirmation gate.

These scripts are not pure skills and are not an OS sandbox. Never mark the
user goal verified merely because a process exited successfully.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path


def _script_root(base_dir):
    root=Path(base_dir).resolve()/'storage/autonomy/skill_scripts'
    if root.resolve()!=root:
        raise ValueError('Unsafe script directory')
    return root


def _allowed_script_roots(base_dir):
    # Preserve hash-pinned legacy records without silently rewriting their authority metadata.
    return (_script_root(base_dir), Path(base_dir).resolve() / 'storage/artifacts/code/skills')


def build_script_skill(store, base_dir, name, purpose, inputs):
    from actions.code_helper import _build
    root=_script_root(base_dir)
    root.mkdir(parents=True,exist_ok=True)
    path=root/(uuid.uuid4().hex+'.py')
    outputs = Path(base_dir).resolve() / 'storage/artifacts/skill_outputs'
    outputs.mkdir(parents=True, exist_ok=True)
    specification=(
        'Create a reusable standalone Python CLI for this purpose. Read current invocation inputs as JSON '
        'from sys.argv[1]; do not hardcode the current input values. Use installed libraries or the standard library. '
        'Do not install packages, change Mark source/security/configuration, invent credentials, select alternate '
        'LLM providers/models or claim unavailable image-generation access. Use only configured authorized '
        'services. If access/dependencies are missing, fail with a clear requirement; do not fabricate success. '
        'For image generation do not substitute local text/geometric rendering for a required image service unless explicitly requested. '
        'Write generated output artifacts under '+str(outputs)+', never beside the skill source. Preserve existing files with unique '
        'names, and print actual result paths. A process exit does not prove content or user-goal completion. '
        'Purpose: '+purpose+'\nInvocation input example (untrusted data, do not hardcode values): '+json.dumps(inputs,ensure_ascii=False))
    raw=_build(specification,'python',str(path),[json.dumps(inputs,ensure_ascii=False)],30,structured=True,working_dir=str(outputs))
    result=json.loads(raw)
    if result.get('process_verified') is not True or result.get('executed') is not True:
        return result
    if Path(result.get('file_path','')).resolve()!=path or not path.is_file():
        raise ValueError('Build returned an unexpected script path')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if result.get('source_sha256')!=digest:
        raise ValueError('Built script integrity mismatch')
    from core.skill_catalog import input_schema
    from core.computation_script import source_assessment
    checked = source_assessment(path)
    low_risk = bool(checked and checked[1]['computation_only'])
    try:
        record=store.create(name,purpose,[{'capability':'code_helper','inputs':{'action':'run','file_path':str(path)}}],
            permissions=() if low_risk else ('server.script.execute',),risk_level='LOW' if low_risk else 'HIGH',
            provenance={'template':'approved_script_v1','source_sha256':digest,'parameters':input_schema(inputs),'risk_assessment':checked[1] if checked else None})
    except Exception as exc:
        result.update(skill_created=False,registration_error_type=type(exc).__name__,
            instruction='The script already executed once successfully, but skill registration failed. Do not rebuild or rerun the task merely to retry registration. Inspect and deliver the existing output; report the persistence failure separately.')
        return result
    # Build already performed the initial execution. Never execute it a second time.
    result.update(skill_id=record['skill_id'],skill_created=True,
        instruction='Script was built, run once and saved for reuse. Verify its actual requested output before delivery or goal completion. Do not run it again merely because registration finished.')
    return result


def run_script_skill(record,base_dir,inputs):
    from actions.code_helper import _run_file
    if record.get('operational_state') not in {'ACTIVE','DEGRADED'} or record.get('skill_type')!='COMPOSITE':
        raise ValueError('Script skill is not active')
    if (record.get('permissions'),record.get('risk_level')) not in [(['server.script.execute'],'HIGH'),([], 'LOW')]:
        raise ValueError('Script authority metadata invalid')
    steps=record.get('steps')
    if not isinstance(steps,list) or len(steps)!=1:
        raise ValueError('Invalid script composition')
    args=steps[0].get('inputs') or {}
    path=Path(args.get('file_path',''))
    root=_script_root(base_dir)
    if path.parent not in _allowed_script_roots(base_dir) or path.suffix!='.py' or path.resolve()!=path:
        raise ValueError('Invalid saved script path')
    if steps!=[{'capability':'code_helper','inputs':{'action':'run','file_path':str(path)}}]:
        raise ValueError('Invalid script composition')
    prov=record.get('provenance') or {}
    if prov.get('template')!='approved_script_v1' or hashlib.sha256(path.read_bytes()).hexdigest()!=prov.get('source_sha256'):
        raise ValueError('Saved script changed; refusing execution')
    from core.computation_script import run_checked
    if record.get('risk_level') == 'LOW':
        result = run_checked(path,[json.dumps(inputs,ensure_ascii=False)],expected_sha256=prov.get('source_sha256'))
        result['skill_id'] = record['skill_id']
        return result
    output_dir = Path(base_dir).resolve() / 'storage/artifacts/skill_outputs' if path.parent == root else path.parent
    output=_run_file(path,[json.dumps(inputs,ensure_ascii=False)],30,False,str(output_dir))
    waiting=output.startswith('WAITING:')
    success=output.startswith('Execution finished (exit_code=0)')
    return {'status':'WAITING' if waiting else 'UNVERIFIED' if success else 'FAILED',
        'verified':False,'process_verified':success,'executed':True,'skill_id':record['skill_id'],
        'file_path':str(path),'output':output,
        'instruction':'Verify the actual requested result before completion. A timeout may have partial side effects; inspect them before retrying.'}


def saved_computation_script(skill_id):
    """Classify the pinned host script, never a model risk label."""
    import re
    from core.computation_script import validated_source
    if not isinstance(skill_id, str) or not re.fullmatch(r'[a-f0-9]{32}', skill_id):return None
    base = Path(__file__).resolve().parents[1]
    try:
        record = json.loads((base / 'storage/autonomy/skills' / (skill_id + '.json')).read_text())
        steps = record.get('steps') or []
        path = Path(steps[0]['inputs']['file_path'])
        provenance = record.get('provenance') or {}
        if (record.get('skill_id') != skill_id or record.get('skill_type') != 'COMPOSITE'
                or record.get('operational_state') not in {'ACTIVE', 'DEGRADED'}
                or (record.get('permissions'),record.get('risk_level')) not in [(['server.script.execute'],'HIGH'),([], 'LOW')]
                or provenance.get('template') != 'approved_script_v1' or path.parent not in _allowed_script_roots(base)
                or steps != [{'capability':'code_helper','inputs':{'action':'run','file_path':str(path)}}]):return None
        source = validated_source(path)
        digest = hashlib.sha256(source.encode()).hexdigest() if source is not None else None
        if digest is None or digest != provenance.get('source_sha256'):return None
        return str(path), digest
    except (OSError, ValueError, KeyError, IndexError, TypeError):return None
