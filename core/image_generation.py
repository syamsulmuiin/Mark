"""Explicit image-generation service selection; never a Text/Live model fallback."""
from __future__ import annotations

import base64
import getpass
import json
import os
import re
import socket
import tempfile
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from core.llm_http import urlopen
from core.setup_config import load_config

MAX_RESPONSE=32*1024*1024
# Hosted NVIDIA endpoints have model-specific payloads, not OpenAI Image API schemas.
NVIDIA_IMAGE_MODELS={
    'black-forest-labs/flux.1-schnell':{'steps':4,'cfg_scale':0},
    'black-forest-labs/flux.1-dev':{'steps':50,'cfg_scale':5},
}


class ImageGenerationError(RuntimeError):
    pass


class ImageGenerationPending(ImageGenerationError):
    pass


def selection(config=None):
    settings=load_config() if config is None else config
    from core.model_profiles import enabled, primary
    if enabled(settings):
        from core.model_profiles import RouteUnavailable
        try:p=primary('image',settings)
        except RouteUnavailable:raise ImageGenerationError('image_route_not_configured') from None
        return selection({'image_generation':{'provider':p['provider'],'model':p['model'],'api_key':p.get('api_key','')}})
    selected=settings.get('image_generation') or {}
    if not isinstance(selected,dict) or selected.get('provider') not in {'gemini','openai','nvidia'}:
        raise ImageGenerationError('image_provider_not_configured')
    model=selected.get('model')
    key=selected.get('api_key')
    if selected['provider']=='nvidia':
        if not isinstance(model,str) or model not in NVIDIA_IMAGE_MODELS:
            raise ImageGenerationError('unsupported_nvidia_image_model')
    elif not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,150}',model):
        raise ImageGenerationError('image_model_not_configured')
    if not isinstance(key,str) or not key.strip():
        raise ImageGenerationError('image_api_key_missing')
    return selected['provider'],model,key.strip()


def _request(provider,key,url,body=None,timeout=120):
    headers={'Content-Type':'application/json','Accept':'application/json'}
    headers['x-goog-api-key' if provider=='gemini' else 'Authorization']=key if provider=='gemini' else 'Bearer '+key
    if provider=='openai' and body is not None:
        headers['Idempotency-Key']=uuid.uuid4().hex
    req=Request(url,data=json.dumps(body).encode() if body is not None else None,headers=headers,
                method='POST' if body is not None else 'GET')
    try:
        with urlopen(req,timeout=timeout) as response:
            if getattr(response,'status',200)==202:
                raise ImageGenerationPending('image_generation_accepted_result_pending')
            raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:
            raise ImageGenerationError('image_response_too_large')
        return json.loads(raw)
    except HTTPError as exc:
        raise ImageGenerationError(f'image_provider_http_{exc.code}') from None
    except (TimeoutError,socket.timeout):
        raise ImageGenerationPending('image_generation_timeout_result_unknown') from None
    except URLError as exc:
        if isinstance(exc.reason,(TimeoutError,socket.timeout)):
            raise ImageGenerationPending('image_generation_timeout_result_unknown') from None
        if body is not None:
            raise ImageGenerationPending('image_generation_connection_result_unknown') from None
        raise ImageGenerationError('image_provider_connection_failed') from None
    except (ValueError,UnicodeError):
        raise ImageGenerationError('invalid_image_provider_response') from None


def generate_image(prompt,base_dir,*,config=None):
    settings=load_config() if config is None else config
    from core.model_profiles import enabled, run
    if enabled(settings):
        def invoke(p,remaining):
            return _generate_image(prompt,base_dir,config={'image_generation':{
                'provider':p['provider'],'model':p['model'],'api_key':p.get('api_key','')}},timeout=remaining)
        return run('image',invoke,settings=settings,timeout=120)
    return _generate_image(prompt,base_dir,config=settings)


def _generate_image(prompt,base_dir,*,config=None,timeout=120):
    from core.image_download import save_image_bytes, MAX_BYTES
    from core.interaction_log import write_event
    provider,model,key=selection(config)
    def event(stage,**fields):
        write_event(base_dir/'runtime/interaction.log','image_generation',stage=stage,provider=provider,model=model,**fields)
    event('started')
    prompt=('Create a finished image appropriate to the requested medium and subject. Infer the needed visual composition. '
            'Do not replace requested illustrative content with a plain text card or geometric placeholder unless requested. '
            'Preserve requested wording, language and year; do not invent official slogans or official status. '
            'User request: '+prompt)
    try:
        if provider=='nvidia':
            if len(prompt)>10000:
                raise ImageGenerationError('nvidia_image_prompt_too_long')
            data=_request(provider,key,'https://ai.api.nvidia.com/v1/genai/'+model,
                {'prompt':prompt,'width':1024,'height':1024,'samples':1,'seed':0,'mode':'base',
                 **NVIDIA_IMAGE_MODELS[model]},timeout=timeout)
            artifacts=data.get('artifacts') or []
            if not artifacts or artifacts[0].get('finishReason') not in {None,'SUCCESS'}:
                raise ImageGenerationError('nvidia_image_blocked_or_incomplete')
            encoded=artifacts[0].get('base64')
        elif provider=='gemini':
            data=_request(provider,key,'https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent',
                {'contents':[{'parts':[{'text':prompt}]}],
                 'generationConfig':{'responseModalities':['TEXT','IMAGE']}},timeout=timeout)
            candidates=data.get('candidates') or []
            if not candidates or candidates[0].get('finishReason') not in {None,'STOP'}:
                raise ImageGenerationError('image_generation_blocked_or_incomplete')
            parts=(candidates[0].get('content') or {}).get('parts') or []
            encoded=next((p['inlineData'].get('data') for p in parts
                if isinstance(p,dict) and isinstance(p.get('inlineData'),dict)
                and str(p['inlineData'].get('mimeType','')).startswith('image/')),None)
        else:
            data=_request(provider,key,'https://api.openai.com/v1/images/generations',
                {'model':model,'prompt':prompt,'n':1},timeout=timeout)
            images=data.get('data') or []
            encoded=images[0].get('b64_json') if images else None
        if not isinstance(encoded,str) or not encoded or len(encoded)>4*((MAX_BYTES+2)//3):
            raise ImageGenerationError('provider_returned_no_supported_image')
        try:
            raw=base64.b64decode(encoded,validate=True)
        except ValueError:
            raise ImageGenerationError('invalid_generated_image_encoding') from None
        artifact=save_image_bytes(raw,base_dir)
        event('succeeded',sha256=artifact['sha256'],size=artifact['size'])
        return artifact,{'provider':provider,'model':model}
    except Exception as exc:
        event('failed',error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,ImageGenerationError) else 'invalid_or_failed_image_response')
        raise


def list_image_models(provider,key):
    """Return catalog candidates, not proof of image-generation entitlement."""
    if provider=='nvidia':
        # This is the implemented-adapter list, not a claim of account entitlement.
        return sorted(NVIDIA_IMAGE_MODELS)
    if provider=='openai':
        data=_request(provider,key,'https://api.openai.com/v1/models',timeout=20)
        return sorted({r['id'] for r in data.get('data',[]) if isinstance(r,dict)
            and isinstance(r.get('id'),str) and r['id'].startswith('gpt-image-')})
    if provider!='gemini':
        raise ValueError('Unsupported image provider')
    names=set();token=''
    for _ in range(4):
        query={'pageSize':100}
        if token:query['pageToken']=token
        data=_request(provider,key,'https://generativelanguage.googleapis.com/v1beta/models?'+urlencode(query),timeout=20)
        for row in data.get('models',[]):
            name=str(row.get('name','')).removeprefix('models/')
            if (name.startswith('gemini') and any(s in name.lower() for s in ('image','banana'))
                    and 'generateContent' in row.get('supportedGenerationMethods',[])):
                names.add(name)
        token=data.get('nextPageToken') or ''
        if not token:break
    return sorted(names)


def save_selection(provider,model,key):
    from core import setup_config
    selected={'provider':provider,'model':model,'api_key':key}
    if provider!='disabled':selection({'image_generation':selected})
    current=load_config();current['image_generation']=selected
    path=setup_config.CONFIG_FILE
    if path.exists():
        try:
            current=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(current,dict):raise ValueError()
        except (ValueError,OSError):
            raise ValueError('Existing server configuration is unreadable; refusing to overwrite it') from None
        current['image_generation']=selected
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as output:
        temp=output.name
        json.dump(current,output,ensure_ascii=False,indent=4)
    try:
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return current


def configure():
    print('Image generation service (separate capability; Text/Live selections remain unchanged).')
    print('1. Google Gemini image API  2. OpenAI Image API  3. Disable  4. NVIDIA NIM hosted image API')
    print('Image generation may incur provider charges. Codex account login is not an Image API key.')
    choice=input('Provider: ').strip()
    if choice=='3':
        save_selection('disabled','','');return
    provider={'1':'gemini','2':'openai','4':'nvidia'}.get(choice)
    if not provider:raise ValueError('Choose a supported provider')
    current=load_config()
    previous=current.get('image_generation') or {}
    retained=previous.get('api_key','') if previous.get('provider')==provider else current.get(provider+'_api_key','')
    key=getpass.getpass('Image API key (blank reuses existing key for the selected provider): ').strip() or retained
    if not key:raise ValueError('An API key is required; account login is not used')
    if provider=='nvidia':
        print('NVIDIA list shows implemented hosted adapters, not verified account access. No local GPU is used.')
    try:
        models=list_image_models(provider,key)
    except Exception:
        print('Model catalog unavailable. Enter an image-capable model ID manually or cancel.')
        models=[]
    for index,model in enumerate(models[:60],1):print(f'{index}. {model}')
    value=input('Model number or exact image model ID: ').strip()
    if value.isdigit() and not 1<=int(value)<=min(len(models),60):
        raise ValueError('Invalid model number')
    model=models[int(value)-1] if value.isdigit() else value
    save_selection(provider,model,key)
    print('Image generation selection saved. No image was generated; access is checked on the first request.')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure',action='store_true')
    args=parser.parse_args()
    try:
        if args.configure:configure()
        else:
            provider,model,_=selection()
            print(json.dumps({'provider':provider,'model':model,'configured':True}))
    except (ValueError,ImageGenerationError,EOFError,KeyboardInterrupt) as exc:
        print(str(exc) if isinstance(exc,(ValueError,ImageGenerationError)) else 'Image setup cancelled')
        raise SystemExit(1)
