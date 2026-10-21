import json
from pathlib import Path
import pytest
from PIL import Image

from actions import image_create as action
from actions import skill_manager as manager
from core.image_design import render_design
from core.action_policy import requires_confirmation


def plan():
    return {'supported':True,'width':600,'height':800,'background':'#ffffff',
            'elements':[{'type':'rectangle','x':0,'y':0,'x2':599,'y2':200,'color':'#008800'},
                        {'type':'text','x':40,'y':50,'size':32,'color':'#ffffff','text':'Hari Santri 2026'}]}


def test_renderer_writes_real_png_without_code_execution(tmp_path):
    result=render_design(plan(),tmp_path)
    with Image.open(result['file_path']) as image:
        assert image.format=='PNG' and image.size==(600,800)
    assert Path(result['file_path']).is_relative_to(tmp_path/'storage/artifacts/images')
    assert result['size']>0 and result['image_verified']
    second=render_design(plan(),tmp_path)
    assert second['file_path']!=result['file_path']


@pytest.mark.parametrize('alter',[
    lambda p:p.update(width=True),lambda p:p.update(height=999999),
    lambda p:p.update(background='https://example.org/image.png'),
    lambda p:p['elements'][0].update(type='exec',code='import os'),
    lambda p:p['elements'][1].update(x=590),
    lambda p:p.update(elements=[p['elements'][0]]*81),
    lambda p:p['elements'][1].update(text='x'*1001),
])
def test_renderer_rejects_unsafe_or_clipped_designs(tmp_path,alter):
    data=plan();alter(data)
    with pytest.raises(ValueError):render_design(data,tmp_path)
    assert not list(tmp_path.rglob('*.png'))


def mock_provider(monkeypatch,tmp_path,matches=True):
    from core import llm_text, llm_visual, image_review
    monkeypatch.setattr(action,'BASE_DIR',tmp_path)
    monkeypatch.setattr(llm_visual,'visual_provider',lambda:({},'openai_codex'))
    monkeypatch.setattr(llm_text,'generate',lambda *a,**kw:json.dumps(plan()))
    monkeypatch.setattr(image_review,'review_images',lambda *a,**kw:[{'matches':matches,'reason':'test','visible_text':'Hari Santri 2026'}])


def test_create_image_returns_reviewed_artifact_not_script(monkeypatch,tmp_path):
    mock_provider(monkeypatch,tmp_path)
    result=json.loads(action.image_create({'prompt':'Buat poster Hari Santri 2026'}))
    assert result['status']=='UNVERIFIED'  # Inbox handoff still required.
    artifact=result['image_artifacts'][0]
    assert artifact['content_verified'] and artifact['file_path'].endswith('.png')
    assert not requires_confirmation('image_create',{'prompt':'poster'})


def test_rejected_design_is_not_eligible_for_delivery(monkeypatch,tmp_path):
    mock_provider(monkeypatch,tmp_path,False)
    result=json.loads(action.image_create({'prompt':'poster'}))
    assert result['status']=='FAILED' and 'image_artifacts' not in result


def test_unsupported_style_does_not_silently_substitute(monkeypatch,tmp_path):
    from core import llm_text
    mock_provider(monkeypatch,tmp_path)
    monkeypatch.setattr(llm_text,'generate',lambda *a,**kw:'{"supported":false}')
    result=json.loads(action.image_create({'prompt':'photorealistic portrait'}))
    assert result['status']=='BLOCKED' and result['reason']=='unsupported_image_style'
    assert not list(tmp_path.rglob('*.png'))


def test_saved_creation_skill_survives_fresh_handler_and_host_gate(monkeypatch,tmp_path):
    from core import skill_registry
    monkeypatch.setattr(manager,'BASE_DIR',tmp_path)
    monkeypatch.setattr(skill_registry,'__file__',str(tmp_path/'core/skill_registry.py'))
    created=json.loads(manager.skill_manager({'operation':'create','kind':'image_create','name':'poster_maker'}))
    sid=created['skill_id']
    assert created['status']=='REGISTERED'
    assert any(r['skill_id']==sid for r in json.loads(manager.skill_manager({'operation':'list'}))['skills'])
    assert not requires_confirmation('skill_manager',{'operation':'create','kind':'image_create'})
    assert not requires_confirmation('skill_manager',{'operation':'run','skill_id':sid})
    calls=[]
    monkeypatch.setattr(action,'image_create',lambda args:calls.append(args) or '{}')
    manager.skill_manager({'operation':'run','skill_id':sid,'inputs':{'prompt':'Make a diagram'}})
    assert calls==[{'prompt':'Make a diagram'}]
    record=manager.SkillRegistry(tmp_path/'storage/autonomy').get(sid)
    record['steps'].append({'capability':'code_helper'})
    manager.SkillRegistry(tmp_path/'storage/autonomy')._save(record)
    assert requires_confirmation('skill_manager',{'operation':'run','skill_id':sid})
    assert json.loads(manager.skill_manager({'operation':'run','skill_id':sid,'inputs':{'prompt':'bad'}}))['status']=='FAILED'
