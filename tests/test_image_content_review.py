import asyncio
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from actions import web_search as search
from core import image_review as review
from core import image_download as download
from core import llm_visual
from core.image_delivery import deliver_image_results


def verdict(index=0, matches=True):
    return {'index':index, 'matches':matches, 'reason':'visible evidence', 'visible_text':'test'}


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path/'image.png'
    Image.new('RGB',(20,30),'blue').save(path)
    return {'file_path':str(path), 'image_verified':True}


@pytest.mark.parametrize('query',['a complete Santri poster with 2026 text','a cat photograph',
    'a logo without text','an electrical circuit diagram','a collage of flower illustrations'])
def test_review_preserves_image_type_and_complete_request(monkeypatch,artifact,query):
    def generate(prompt,images,**kw):
        assert query in prompt
        assert 'untrusted data' in prompt
        assert len(images)==1
        import base64
        assert Image.open(io.BytesIO(base64.b64decode(images[0]))).format=='JPEG'
        return json.dumps({'images':[verdict()]})
    monkeypatch.setattr(review,'generate_visual',generate)
    assert review.review_images(query,[artifact])[0]['matches'] is True


@pytest.mark.parametrize('items',[
    [], [verdict(matches='true')], [verdict(index=True)], [verdict(index=5)],
    [{**verdict(),'reason':''}], [{**verdict(),'visible_text':None}],
])
def test_invalid_visual_verdict_fails_closed(monkeypatch,artifact,items):
    monkeypatch.setattr(review,'generate_visual',lambda *a,**kw:json.dumps({'images':items}))
    with pytest.raises(ValueError): review.review_images('poster',[artifact])


def test_duplicate_review_indices_rejected(monkeypatch,artifact):
    monkeypatch.setattr(review,'generate_visual',lambda *a,**kw:json.dumps({'images':[verdict(),verdict()]}))
    with pytest.raises(ValueError):review.review_images('photos',[artifact,artifact])


def test_search_replenishes_rejections_and_deduplicates(monkeypatch,tmp_path):
    monkeypatch.setattr(llm_visual,'visual_provider',lambda: ({},'openai_codex'))
    monkeypatch.setattr(search,'BASE_DIR',tmp_path)
    monkeypatch.setattr(search,'_ddg_available',lambda:True)
    class Engine:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def images(self,query,**kw):
            assert kw['max_results']==15
            return [{'image':f'https://example.org/{i}.png'} for i in range(12)]
    monkeypatch.setattr(search,'_get_ddgs',lambda:Engine)
    monkeypatch.setattr(download,'save_verified_image',lambda url,base:{'file_path':url,'image_verified':True})
    monkeypatch.setattr(review,'preview',lambda a: 'same' if a['file_path'].rsplit('/',1)[-1] in {'0.png','1.png'} else a['file_path'])
    seen=[]
    def inspect(query,batch,**kw):
        seen.extend(a['file_path'] for a in batch)
        return [verdict(i,not a['file_path'].endswith(('2.png','3.png','4.png'))) for i,a in enumerate(batch)]
    monkeypatch.setattr(review,'review_images',inspect)
    result=json.loads(search.web_search({'query':'five complete posters','mode':'images','count':5}))
    assert result['matched_count']==5 and not result['partial']
    assert len(seen)>5  # Rejected candidates were replaced from subsequent candidates.
    assert len(result['rejected_candidates'])==4
    assert all(a['content_verified'] for a in result['image_artifacts'])
    assert not any(a['file_path'].endswith(('1.png','2.png','3.png','4.png')) for a in result['image_artifacts'])


def test_unsupported_provider_never_downloads_or_falls_back(monkeypatch):
    from core.setup_config import load_config
    monkeypatch.setattr(llm_visual,'load_config',lambda:{'llm_provider':'deepseek'})
    monkeypatch.setattr(search,'_get_ddgs',lambda:pytest.fail('search should not run'))
    result=json.loads(search.web_search({'query':'poster','mode':'images'}))
    assert result['status']=='BLOCKED' and result['reason']=='visual_review_unavailable'


def test_delivery_rejects_unreviewed_and_distinguishes_partial_goal():
    class Dashboard:
        _mesh=SimpleNamespace(get=lambda _: {'capabilities':['attachment.inbox']})
        async def send_server_file(self,*args):return {'ok':True,'attachment_id':'id'}
    payload={'image_artifacts':[{'file_path':'image.png','image_verified':True}], 'requested_count':5}
    result=json.loads(asyncio.run(deliver_image_results(payload,Dashboard(),'phone')))
    assert result['delivered_count']==0 and not result['verified']
    payload['image_artifacts'][0]['content_verified']=True
    payload['partial']=True
    result=json.loads(asyncio.run(deliver_image_results(payload,Dashboard(),'phone')))
    assert result['status']=='PARTIAL' and result['delivery_verified'] and not result['goal_verified']


@pytest.mark.parametrize('provider,module',[
    ('openai_codex','core.llm_codex'),('anthropic','core.llm_anthropic'),
    ('google_oauth','core.llm_google_oauth'),('openai','core.llm_compatible'),
    ('openrouter','core.llm_compatible'),('ollama_local','core.llm_compatible')])
def test_review_routes_only_primary_model(monkeypatch,provider,module):
    import importlib
    calls=[]
    monkeypatch.setattr(importlib.import_module(module),'generate_text',lambda *a,**kw:calls.append((a,kw)) or '{}')
    monkeypatch.setattr(llm_visual,'traced_text_call',lambda p,m,run:run())
    result=llm_visual.generate_visual('review',['AA=='],config={'llm_provider':provider,
        'provider_models':{provider:'chosen-model,ignored-fallback'},provider+'_api_key':'test'})
    assert result=='{}' and len(calls)==1
    assert 'chosen-model' in calls[0][0] and calls[0][1]['images']==['AA==']


@pytest.mark.parametrize('provider',['openai','anthropic','openai_codex','google_oauth'])
def test_image_adapter_wire_payload(monkeypatch,provider):
    import importlib
    module=importlib.import_module({'openai':'core.llm_compatible','anthropic':'core.llm_anthropic',
        'openai_codex':'core.llm_codex','google_oauth':'core.llm_google_oauth'}[provider])
    captured=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def __iter__(self):
            yield b'data: '+json.dumps({'type':'response.completed','response':{'status':'completed',
                'output':[{'type':'message','content':[{'type':'output_text','text':'ok'}]}]}}).encode()
        def read(self,*a):
            return json.dumps({'choices':[{'message':{'content':'ok'}}],
                'content':[{'type':'text','text':'ok'}], 'stop_reason':'end_turn',
                'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'ok'}]}}]}).encode()
    monkeypatch.setattr(module,'urlopen',lambda request,**kw:captured.append(json.loads(request.data)) or Response())
    if provider=='openai_codex':
        monkeypatch.setattr(module,'check_login',lambda:{'access_token':'test','account_id':'test'})
        module.generate_text('model','request',images=['AA=='])
        assert captured[0]['input'][0]['content'][1]=={'type':'input_image','image_url':'data:image/jpeg;base64,AA=='}
    elif provider=='google_oauth':
        monkeypatch.setattr(module,'credentials',lambda:(SimpleNamespace(token='test'),'project'))
        module.generate_text('model','request',images=['AA=='])
        assert captured[0]['contents'][0]['parts'][1]['inlineData']=={'mimeType':'image/jpeg','data':'AA=='}
    elif provider=='anthropic':
        module.generate_text('model','request',api_key='test',images=['AA=='])
        assert captured[0]['messages'][0]['content'][0]['source']=={'type':'base64','media_type':'image/jpeg','data':'AA=='}
    else:
        module.generate_text('openai','model','request',api_key='test',images=['AA=='])
        assert captured[0]['messages'][0]['content'][1]['image_url']['url']=='data:image/jpeg;base64,AA=='


def test_gemini_image_route_uses_primary_text_only(monkeypatch):
    from core import gemini
    calls=[]
    monkeypatch.setattr(llm_visual,'traced_text_call',lambda p,m,run:run())
    monkeypatch.setattr(gemini,'text',lambda parts,**kw:calls.append((parts,kw)) or '{}')
    assert llm_visual.generate_visual('review',['AA=='],config={'llm_provider':'gemini'})=='{}'
    assert len(calls)==1 and calls[0][1]['tier']==gemini.SMART
    assert calls[0][0][1].inline_data.mime_type=='image/jpeg'


@pytest.mark.parametrize('stop',['failure','budget'])
def test_incomplete_review_never_delivers_unreviewed_candidates(monkeypatch,tmp_path,stop):
    monkeypatch.setattr(llm_visual,'visual_provider',lambda:({},'openai'))
    monkeypatch.setattr(search,'BASE_DIR',tmp_path)
    monkeypatch.setattr(search,'_ddg_available',lambda:True)
    class Engine:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def images(self,*a,**kw):return [{'image':'https://example.org/image.png'}]
    monkeypatch.setattr(search,'_get_ddgs',lambda:Engine)
    monkeypatch.setattr(search,'_note_ddg_failure',lambda _:pytest.fail('review failure is not a search outage'))
    monkeypatch.setattr(download,'save_verified_image',lambda *a:{'file_path':'image.png','image_verified':True})
    monkeypatch.setattr(review,'preview',lambda a:'test')
    def fail(*a,**kw):raise ValueError('token=private')
    monkeypatch.setattr(review,'review_images',fail)
    if stop=='budget':
        import time
        ticks=iter([0,0,100])
        monkeypatch.setattr(time,'monotonic',lambda:next(ticks,100))
    result=json.loads(search.web_search({'query':'photo','mode':'images','count':1}))
    assert not result['image_artifacts'] and not result['verified']
    assert result['stop_reason']==('visual_review_failed' if stop=='failure' else 'review_budget_exhausted')
    assert 'private' not in json.dumps(result)
