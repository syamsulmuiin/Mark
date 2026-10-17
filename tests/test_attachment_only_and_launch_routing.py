import ast
import asyncio
import json
from pathlib import Path
import secrets
import shutil
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlsplit
import pytest
from core.attachment_inbox import AttachmentInbox
from core.file_store import ObjectStore
from core.server_export_policy import approve_server_export, validate_delivery_name
from core.companion_routing import normalize_companion_call
from core.runtime_errors import classify_error, Boundary, ErrorAction

ROOT=Path(__file__).resolve().parents[1]


def _method(path, cls_name, method_name, namespace):
    tree=ast.parse((ROOT/path).read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls_name)
    method=next(n for n in cls.body if getattr(n,'name','')==method_name)
    method.decorator_list=[]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),path,'exec'),namespace)
    return namespace[method_name]


@pytest.mark.parametrize('online',[True,False])
@pytest.mark.parametrize('direct_flag',[False, 'false', None])
def test_default_delivery_stays_attachment_despite_destination_argument(tmp_path,online,direct_flag):
    runtime=tmp_path/'runtime';runtime.mkdir()
    source=runtime/'error.log';source.write_text('diagnostic evidence')
    messages=[]
    class Socket:
        async def send_json(self,message): messages.append(message)
    async def forbidden(*a,**kw): pytest.fail('must never call file.receive')
    host=NS(_file_store=ObjectStore(tmp_path/'objects'),
            _attachment_inbox=AttachmentInbox(tmp_path/'metadata'),
            _device_sockets={'phone':Socket()} if online else {},call_device=forbidden)
    namespace={'BASE_DIR':tmp_path,'approve_server_export':approve_server_export,
               'validate_delivery_name':validate_delivery_name,'secrets':secrets,'shutil':shutil,
               '_safe_filename':lambda name:name,'_interaction_event':lambda *a,**k:None}
    method=_method('dashboard/server.py','DashboardServer','send_server_file',namespace)
    result=asyncio.run(method(host,'phone','runtime/error.log','friendly.txt',
                             save_direct=direct_flag,destination='Downloads/Mark'))
    assert result['ok'] is True
    assert result['saved_to_destination'] is False
    assert result['name']=='friendly.log'
    assert result['status']==('notified' if online else 'queued')
    stored=AttachmentInbox(tmp_path/'metadata').get('phone',result['attachment_id'])
    assert stored['source_path']=='runtime/error.log'
    assert source.read_text()=='diagnostic evidence'
    if online: assert messages[0]['type']=='attachment.new'
    else: assert not messages


def test_generic_device_call_cannot_bypass_attachment_policy():
    signature=lambda *a:'signature'
    method=_method('main.py','JarvisLive','_guard_device_action',{})
    host=NS(_device_action_signature=signature,_blocked_device_action=None)
    sig,error=method(host,'phone','file.receive',{'url':'https://example.invalid/file'})
    assert sig=='signature'
    assert 'send_server_file' in error


def test_unverified_or_failed_device_json_blocks_blind_retry():
    method=_method('main.py','JarvisLive','_device_action_rejected',{'json':json})
    assert method(json.dumps({'ok':True,'status':'UNVERIFIED','result':'opened app'}))
    assert method(json.dumps({'ok':False,'status':'FAILED','result':'not found'}))
    assert not method(json.dumps({'ok':True,'status':'SUCCESS','verified':True,'result':'opened app'}))


def test_android_browser_open_alias_respects_advertised_executor():
    assert normalize_companion_call('browser.open',{'url':'https://example.com'}, {'open_url'}) == (
        'open_url',{'url':'https://example.com'})
    assert normalize_companion_call('browser.open',{'url':'https://example.com'}, {'browser.open'}) == (
        'browser.open',{'url':'https://example.com'})
    with pytest.raises(ValueError):
        normalize_companion_call('browser.open',{'url':'intent://unrequested'}, {'open_url'})


def test_android_search_alias_encodes_query_without_server_browser():
    cap,args=normalize_companion_call('browser.search',{'query':'a & b # c'}, {'open_url'})
    assert cap=='open_url'
    assert parse_qs(urlsplit(args['url']).query)=={'q':['a & b # c']}


@pytest.mark.parametrize('message,action',[
    ('1011 None. Deadline expired before operation could complete.',ErrorAction.TRANSPORT_RECONNECT),
    ('1008 None. Requested entity was not found.',ErrorAction.MODEL_FAILOVER),
])
def test_taskgroup_error_preserves_nested_provider_cause(message,action):
    group=ExceptionGroup('unhandled errors in a TaskGroup',[RuntimeError(message)])
    assert classify_error(Boundary.LIVE_SESSION,group).action is action


def test_android_launch_waits_for_real_foreground_and_reports_unverified():
    src=(ROOT/'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text()
    block=src[src.index('"app.launch"->{'):src.index('"app.close"->{')]
    assert 'runOnUiThread' in block
    assert 'SystemClock.elapsedRealtime()+3000L' in block
    assert 'Thread.sleep(350)' not in block
    assert 'accessibility_observation_unavailable' in block
    assert 'foreground was not verified' in block
    assert 'val mime=attachmentMime(name)' in src
