import hashlib
import json
from pathlib import Path

import pytest
from actions import skill_manager as manager
from core.action_policy import requires_confirmation
from core import script_skills


def payload(kind='pure'):
    return {'operation':'ensure','kind':kind,'name':'sum_values','purpose':'Sum input values',
            'inputs':{'values':[2,3]}}


def candidate(code='return sum(kwargs["values"])'):
    return {'name':'model_name','description':'Model description',
        'code':'def execute(**kwargs):\n    '+code,
        'tests':[{'input':{'values':[2,3]},'expected':5}]}


def test_pure_ensure_creates_tests_runs_and_reuses_after_fresh_handler(monkeypatch,tmp_path):
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    calls=[]
    class Synth:
        def synthesize(self,*args):calls.append(args);return candidate()
    monkeypatch.setattr(manager,'SkillSynthesizer',Synth)
    first=json.loads(manager.skill_manager(payload()))
    assert first['status']=='SUCCESS' and first['result']==5
    assert first['fulfillment_stage']=='executed_original_inputs'
    second=json.loads(manager.skill_manager({**payload(),'inputs':{'values':[10,20]}}))
    assert second['result']==30 and second['skill_id']==first['skill_id']
    assert second['skill_reused'] and len(calls)==1


def test_failed_pure_candidate_repaired_once_then_original_inputs_run(monkeypatch,tmp_path):
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    calls=[]
    class Synth:
        def synthesize(self,*args):
            calls.append(args)
            return candidate('return 0') if len(calls)==1 else candidate()
    monkeypatch.setattr(manager,'SkillSynthesizer',Synth)
    result=json.loads(manager.skill_manager(payload()))
    assert result['status']=='SUCCESS' and result['result']==5
    assert len(calls)==2 and 'crucible_failed' in calls[1][1]
    assert len(json.loads(manager.skill_manager({'operation':'list'}))['skills'])==1


@pytest.mark.parametrize('source',['import os\ndef execute(**kwargs):\n    return os.getcwd()',
    'def execute(**kwargs):\n    return 0'])
def test_pure_failures_are_bounded_and_never_registered(monkeypatch,tmp_path,source):
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    calls=[]
    class Synth:
        def synthesize(self,*args):
            calls.append(args)
            return {**candidate(),'code':source}
    monkeypatch.setattr(manager,'SkillSynthesizer',Synth)
    result=json.loads(manager.skill_manager(payload()))
    assert result['status']=='FAILED' and len(calls)==2
    assert json.loads(manager.skill_manager({'operation':'list'}))['skills']==[]


def test_pure_ensure_rejects_smoke_tests_without_expected_values(monkeypatch,tmp_path):
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    class Synth:
        def synthesize(self,*args):return {**candidate(),'tests':[{'input':{}}]}
    monkeypatch.setattr(manager,'SkillSynthesizer',Synth)
    assert json.loads(manager.skill_manager(payload()))['status']=='FAILED'
    assert json.loads(manager.skill_manager({'operation':'list'}))['skills']==[]


def test_script_build_executes_once_then_persists_and_reuses_pinned_source(monkeypatch,tmp_path):
    from actions import code_helper
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    builds,runs=[],[]
    def build(description,language,path,args,timeout,**kw):
        builds.append(args)
        Path(path).write_text('print("test")')
        return json.dumps({'process_verified':True,'executed':True,'status':'UNVERIFIED','verified':False,
            'file_path':path,'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()})
    monkeypatch.setattr(code_helper,'_build',build)
    monkeypatch.setattr(code_helper,'_run_file',lambda *a:runs.append(a) or 'Execution finished (exit_code=0)\nOutput:\ntest')
    request={**payload('script'),'inputs':{'values':[2,3]}}
    first=json.loads(manager.skill_manager(request))
    assert first['skill_created'] and len(builds)==1 and not runs
    assert not first['verified']
    second=json.loads(manager.skill_manager(request))
    assert second['skill_reused'] and len(builds)==1 and len(runs)==1
    assert json.loads(runs[0][1][0])==request['inputs']
    Path(first['file_path']).write_text('print("changed")')
    assert json.loads(manager.skill_manager(request))['status']=='FAILED'
    assert len(runs)==1


def test_script_timeout_is_not_registered_or_reexecuted(monkeypatch,tmp_path):
    from actions import code_helper
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    calls=[]
    monkeypatch.setattr(code_helper,'_build',lambda *a,**kw:calls.append(a) or json.dumps({'status':'WAITING','verified':False}))
    result=json.loads(manager.skill_manager(payload('script')))
    assert result['status']=='WAITING' and len(calls)==1
    assert json.loads(manager.skill_manager({'operation':'list'}))['skills']==[]


def test_fixed_image_ensure_executes_original_request_and_reuses(monkeypatch,tmp_path):
    from actions import image_create
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    calls=[]
    monkeypatch.setattr(image_create,'image_create',lambda args:calls.append(args) or '{"status":"UNVERIFIED","image_artifacts":[]}')
    args={**payload('image_create'),'name':'design','inputs':{'prompt':'Create a diagram'}}
    first=json.loads(manager.skill_manager(args));second=json.loads(manager.skill_manager(args))
    assert first['skill_id']==second['skill_id'] and len(calls)==2
    assert calls[0]==args['inputs']


def test_ensure_cannot_relabel_script_or_overwrite_existing_purpose(monkeypatch,tmp_path):
    from core.skill_registry import SkillRegistry
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    store=SkillRegistry(tmp_path/'storage/autonomy')
    record=store.create('sum_values','Other purpose',[{'capability':'code_helper','inputs':{}}],
        provenance={'template':'approved_script_v1'})
    assert json.loads(manager.skill_manager(payload('image_create')))['status']=='FAILED'
    assert store.get(record['skill_id'])['purpose']=='Other purpose'
    assert requires_confirmation('skill_manager',payload('script'))
    assert not requires_confirmation('skill_manager',payload('pure'))
    assert not requires_confirmation('skill_manager',payload('image_create'))


def test_structured_build_reports_process_only_and_exact_source_hash(monkeypatch,tmp_path):
    from actions import code_helper
    path=tmp_path/'test.py';path.write_text('print("hello")')
    monkeypatch.setattr(code_helper,'_write',lambda *a:('print("hello")',path))
    monkeypatch.setattr(code_helper,'_run_file',lambda *a:'Execution finished (exit_code=0)\nOutput:\nhello')
    result=json.loads(code_helper._build('task','python',str(path),[],30,structured=True))
    assert result['process_verified'] and result['executed'] and not result['verified']
    assert result['source_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()


def test_script_workflow_real_subprocess_creates_output_then_reuses(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from actions import code_helper
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    source='''import json, sys
from pathlib import Path
inputs=json.loads(sys.argv[1])
counter=Path('counter.txt')
counter.write_text(str(int(counter.read_text())+1 if counter.exists() else 1))
result=Path('result.json')
result.write_text(json.dumps({'sum':sum(inputs['values'])}))
print(str(result.resolve()))
'''
    monkeypatch.setattr(code_helper,'_get_gemini',lambda:SimpleNamespace(generate_content=lambda _:SimpleNamespace(text=source)))
    first=json.loads(manager.skill_manager(payload('script')))
    root=tmp_path/'storage/artifacts/skill_outputs'
    assert Path(first['file_path']).parent == tmp_path/'storage/autonomy/skill_scripts'
    assert first['process_verified'] and not first['verified']
    assert (root/'counter.txt').read_text()=='1'
    assert json.loads((root/'result.json').read_text())=={'sum':5}
    monkeypatch.setattr(code_helper,'_get_gemini',lambda:pytest.fail('saved script should not regenerate'))
    second=json.loads(manager.skill_manager({**payload('script'),'inputs':{'values':[10,20]}}))
    assert second['skill_id']==first['skill_id'] and second['process_verified']
    assert (root/'counter.txt').read_text()=='2'
    assert json.loads((root/'result.json').read_text())=={'sum':30}


def test_registration_failure_preserves_execution_evidence(monkeypatch,tmp_path):
    from actions import code_helper
    def build(description,language,path,args,timeout,**kw):
        Path(path).write_text('print("done")')
        return json.dumps({'status':'UNVERIFIED','verified':False,'process_verified':True,'executed':True,
            'file_path':path,'source_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()})
    monkeypatch.setattr(code_helper,'_build',build)
    class Store:
        def create(self,*a,**kw):raise OSError('private=detail')
    result=script_skills.build_script_skill(Store(),tmp_path,'task','purpose',{})
    assert result['executed'] and result['process_verified'] and not result['skill_created']
    assert 'Do not rebuild or rerun' in result['instruction']
    assert 'private' not in json.dumps(result)
