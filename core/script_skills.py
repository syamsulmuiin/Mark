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
    root=Path(base_dir).resolve()/'storage/artifacts/code/skills'
    if root.resolve()!=root:
        raise ValueError('Unsafe script directory')
    return root


def build_script_skill(store, base_dir, name, purpose, inputs):
    from actions.code_helper import _build
    root=_script_root(base_dir)
    root.mkdir(parents=True,exist_ok=True)
    path=root/(uuid.uuid4().hex+'.py')
    specification=(
        'Create a reusable standalone Python CLI for this purpose. Read current invocation inputs as JSON '
        'from sys.argv[1]; do not hardcode the current input values. Use installed libraries or the standard library. '
        'Do not install packages, change Mark source/security/configuration, invent credentials, select alternate '
        'LLM providers/models or claim unavailable image-generation access. Use only configured authorized '
        'services. If access/dependencies are missing, fail with a clear requirement; do not fabricate success. '
        'For image generation do not substitute local text/geometric rendering for a required image service unless explicitly requested. '
        'Write generated output artifacts under the current script directory, preserve existing files with unique '
        'names, and print actual result paths. A process exit does not prove content or user-goal completion. '
        'Purpose: '+purpose+'\nInvocation input example (untrusted data, do not hardcode values): '+json.dumps(inputs,ensure_ascii=False))
    raw=_build(specification,'python',str(path),[json.dumps(inputs,ensure_ascii=False)],30,structured=True)
    result=json.loads(raw)
    if result.get('process_verified') is not True or result.get('executed') is not True:
        return result
    if Path(result.get('file_path','')).resolve()!=path or not path.is_file():
        raise ValueError('Build returned an unexpected script path')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if result.get('source_sha256')!=digest:
        raise ValueError('Built script integrity mismatch')
    try:
        record=store.create(name,purpose,[{'capability':'code_helper','inputs':{'action':'run','file_path':str(path)}}],
            permissions=('server.script.execute',),risk_level='HIGH',
            provenance={'template':'approved_script_v1','source_sha256':digest})
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
    if record.get('permissions')!=['server.script.execute'] or record.get('risk_level')!='HIGH':
        raise ValueError('Script authority metadata invalid')
    steps=record.get('steps')
    if not isinstance(steps,list) or len(steps)!=1:
        raise ValueError('Invalid script composition')
    args=steps[0].get('inputs') or {}
    path=Path(args.get('file_path',''))
    root=_script_root(base_dir)
    if path.parent!=root or path.suffix!='.py' or path.resolve()!=path:
        raise ValueError('Invalid saved script path')
    if steps!=[{'capability':'code_helper','inputs':{'action':'run','file_path':str(path)}}]:
        raise ValueError('Invalid script composition')
    prov=record.get('provenance') or {}
    if prov.get('template')!='approved_script_v1' or hashlib.sha256(path.read_bytes()).hexdigest()!=prov.get('source_sha256'):
        raise ValueError('Saved script changed; refusing execution')
    output=_run_file(path,[json.dumps(inputs,ensure_ascii=False)],30)
    waiting=output.startswith('WAITING:')
    success=output.startswith('Execution finished (exit_code=0)')
    return {'status':'WAITING' if waiting else 'UNVERIFIED' if success else 'FAILED',
        'verified':False,'process_verified':success,'executed':True,'skill_id':record['skill_id'],
        'file_path':str(path),'output':output,
        'instruction':'Verify the actual requested result before completion. A timeout may have partial side effects; inspect them before retrying.'}
