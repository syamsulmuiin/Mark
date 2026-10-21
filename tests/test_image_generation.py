import base64
import io
import json
import socket
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from PIL import Image
from core import image_generation as gen
from actions import image_create as action


def config(provider='gemini'):
    return {'image_generation':{'provider':provider,'model':'chosen-image-model','api_key':'private-key'},
            'llm_provider':'openai_codex','live_provider':'gemini'}


def encoded():
    output=io.BytesIO();Image.new('RGB',(10,12),'green').save(output,format='PNG')
    return base64.b64encode(output.getvalue()).decode()


@pytest.mark.parametrize('provider',['gemini','openai'])
def test_fixed_provider_generation_payload_and_real_saved_bytes(monkeypatch,tmp_path,provider):
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,*a):
            return json.dumps({'data':[{'b64_json':encoded()}], 'candidates':[{'finishReason':'STOP',
                'content':{'parts':[{'inlineData':{'mimeType':'image/png','data':encoded()}}]}}]}).encode()
    monkeypatch.setattr(gen,'urlopen',lambda req,**kw:calls.append(req) or Response())
    artifact,origin=gen.generate_image('Buat poster Hari Santri 2026',tmp_path,config=config(provider))
    with Image.open(artifact['file_path']) as image:assert image.size==(10,12) and image.format=='PNG'
    assert origin=={'provider':provider,'model':'chosen-image-model'}
    assert len(calls)==1
    body=json.loads(calls[0].data)
    if provider=='gemini':
        assert calls[0].full_url=='https://generativelanguage.googleapis.com/v1beta/models/chosen-image-model:generateContent'
        assert body['generationConfig']['responseModalities']==['TEXT','IMAGE']
        assert calls[0].get_header('X-goog-api-key')=='private-key'
    else:
        assert calls[0].full_url=='https://api.openai.com/v1/images/generations'
        assert body['model']=='chosen-image-model' and body['n']==1
        assert calls[0].get_header('Authorization')=='Bearer private-key'
    log=(tmp_path/'runtime/interaction.log').read_text()
    assert 'private-key' not in log and 'Buat poster' not in log


def test_no_implicit_selection_from_text_live_or_codex_credentials():
    with pytest.raises(gen.ImageGenerationError,match='image_provider_not_configured'):
        gen.selection({'llm_provider':'openai_codex','gemini_api_key':'existing-live-key','openai_api_key':'existing-key'})
    for model in ('../bad','https://example.org','a/b',''):
        settings=config();settings['image_generation']['model']=model
        with pytest.raises(gen.ImageGenerationError):gen.selection(settings)


@pytest.mark.parametrize('response',[{'data':[{'url':'http://127.0.0.1/image'}]},
    {'data':[{'b64_json':'not base64'}]}, {'data':[{'b64_json':base64.b64encode(b'<html>not image</html>').decode()}]}])
def test_no_remote_image_url_fetch_or_invalid_image_delivery(monkeypatch,tmp_path,response):
    monkeypatch.setattr(gen,'_request',lambda *a,**kw:response)
    with pytest.raises(Exception):gen.generate_image('poster',tmp_path,config=config('openai'))
    assert not list(tmp_path.rglob('*.png'))


def test_http_errors_are_sanitized_without_retry(monkeypatch,tmp_path):
    calls=[]
    def fail(request,**kw):
        calls.append(request)
        raise HTTPError('https://private-key.example',403,'private-key',None,None)
    monkeypatch.setattr(gen,'urlopen',fail)
    with pytest.raises(gen.ImageGenerationError,match='image_provider_http_403'):
        gen.generate_image('poster',tmp_path,config=config())
    assert len(calls)==1 and 'private-key' not in (tmp_path/'runtime/interaction.log').read_text()


@pytest.mark.parametrize('reason',[socket.timeout(),ConnectionResetError('private-connection-detail')])
def test_timeout_remains_unknown_and_does_not_retry(monkeypatch,tmp_path,reason):
    calls=[]
    def fail(request,**kw):calls.append(request);raise URLError(reason)
    monkeypatch.setattr(gen,'urlopen',fail)
    with pytest.raises(gen.ImageGenerationPending):gen.generate_image('poster',tmp_path,config=config())
    assert len(calls)==1


def test_default_creation_never_uses_local_renderer_when_unconfigured(monkeypatch,tmp_path):
    from core import image_design, llm_text
    monkeypatch.setattr(action,'BASE_DIR',tmp_path)
    monkeypatch.setattr(gen,'load_config',lambda:{})
    monkeypatch.setattr(image_design,'render_design',lambda *a:pytest.fail('local substitution'))
    monkeypatch.setattr(llm_text,'generate',lambda *a,**kw:pytest.fail('local planning'))
    result=json.loads(action.image_create({'prompt':'Buat poster Hari Santri 2026'}))
    assert result['status']=='BLOCKED' and result['reason']=='image_provider_not_configured'


def test_default_creation_uses_one_configured_service_and_review(monkeypatch,tmp_path):
    from core import llm_visual,image_review,image_design
    monkeypatch.setattr(action,'BASE_DIR',tmp_path)
    monkeypatch.setattr(gen,'load_config',lambda:config())
    monkeypatch.setattr(llm_visual,'visual_provider',lambda:({},'openai_codex'))
    monkeypatch.setattr(image_design,'render_design',lambda *a:pytest.fail('local substitution'))
    calls=[]
    monkeypatch.setattr(gen,'generate_image',lambda *a:calls.append(a) or ({'file_path':'real.png','image_verified':True},{'provider':'gemini','model':'chosen'}))
    monkeypatch.setattr(image_review,'review_images',lambda *a,**kw:[{'matches':True,'reason':'reviewed','visible_text':'2026'}])
    result=json.loads(action.image_create({'prompt':'Buat poster Hari Santri 2026'}))
    assert len(calls)==1 and result['image_artifacts'][0]['content_verified']
    assert result['generation']['provider']=='gemini' and result['verified'] is False


def test_configuration_preserves_text_live_and_writes_private_file(monkeypatch,tmp_path):
    from core import setup_config
    original=config();original.pop('image_generation')
    monkeypatch.setattr(gen,'load_config',lambda:dict(original))
    path=tmp_path/'config/api_keys.json'
    monkeypatch.setattr(setup_config,'CONFIG_FILE',path)
    result=gen.save_selection('gemini','selected-image-model','secret')
    assert result['llm_provider']=='openai_codex' and result['live_provider']=='gemini'
    assert json.loads(path.read_text())['image_generation']['api_key']=='secret'
    assert path.stat().st_mode & 0o777==0o600


def test_catalog_filters_text_models_and_keeps_image_candidates(monkeypatch):
    monkeypatch.setattr(gen,'_request',lambda *a,**kw:{'models':[
        {'name':'models/gemini-text','supportedGenerationMethods':['generateContent']},
        {'name':'models/gemini-image-model','supportedGenerationMethods':['generateContent']},
        {'name':'models/imagen-model','supportedGenerationMethods':['predict']}]})
    assert gen.list_image_models('gemini','key')==['gemini-image-model']
    monkeypatch.setattr(gen,'_request',lambda *a,**kw:{'data':[{'id':'gpt-text'},{'id':'gpt-image-example'}]})
    assert gen.list_image_models('openai','key')==['gpt-image-example']


def test_wizard_selects_catalog_model_and_reuses_key_only_after_choice(monkeypatch,tmp_path,capsys):
    from core import setup_config
    monkeypatch.setattr(setup_config,'CONFIG_FILE',tmp_path/'api_keys.json')
    current={'llm_provider':'openai_codex','live_provider':'gemini','gemini_api_key':'keep-private'}
    monkeypatch.setattr(gen,'load_config',lambda:dict(current))
    choices=iter(['1','1'])
    monkeypatch.setattr('builtins.input',lambda _:next(choices))
    monkeypatch.setattr(gen.getpass,'getpass',lambda _: '')
    monkeypatch.setattr(gen,'list_image_models',lambda p,k:['catalog-image-model'] if (p,k)==('gemini','keep-private') else [])
    gen.configure()
    saved=json.loads(setup_config.CONFIG_FILE.read_text())
    assert saved['image_generation']=={'provider':'gemini','model':'catalog-image-model','api_key':'keep-private'}
    assert saved['llm_provider']=='openai_codex'
    assert 'keep-private' not in capsys.readouterr().out


def test_corrupt_server_configuration_is_not_overwritten(monkeypatch,tmp_path):
    from core import setup_config
    path=tmp_path/'api_keys.json';path.write_text('{broken')
    monkeypatch.setattr(setup_config,'CONFIG_FILE',path)
    monkeypatch.setattr(gen,'load_config',lambda:{})
    with pytest.raises(ValueError,match='refusing to overwrite'):
        gen.save_selection('gemini','image-model','secret')
    assert path.read_text()=='{broken'
