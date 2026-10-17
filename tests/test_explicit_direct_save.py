import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import threading
from types import SimpleNamespace as NS
import pytest
from core.attachment_inbox import AttachmentInbox
from core.file_store import ObjectStore
from core.server_export_policy import approve_server_export, validate_delivery_name
from test_attachment_only_and_launch_routing import _method, ROOT


@pytest.mark.parametrize('destination',['/home/user/Documents/report.log','Documents/Reports','Downloads/Mark',''])
def test_explicit_direct_save_forwards_requested_destination(tmp_path,destination):
    (tmp_path/'runtime').mkdir()
    (tmp_path/'runtime'/'report.log').write_text('evidence')
    calls=[]
    async def call(device,cap,args,**kwargs):
        calls.append((device,cap,args))
        return {'ok':True,'verified':True,'status':'SUCCESS','result':'saved at chosen destination'}
    host=NS(_file_store=ObjectStore(tmp_path/'objects'),_attachment_inbox=AttachmentInbox(tmp_path/'metadata'),
            _device_sockets={},call_device=call,get_remote_url=lambda:'https://server.invalid',
            _new_transfer_ticket=lambda *a,**k:'ticket')
    namespace={'BASE_DIR':tmp_path,'approve_server_export':approve_server_export,
               'validate_delivery_name':validate_delivery_name,'secrets':secrets,'shutil':shutil,
               '_safe_filename':lambda name:name,'_interaction_event':lambda *a,**k:None}
    method=_method('dashboard/server.py','DashboardServer','send_server_file',namespace)
    result=asyncio.run(method(host,'phone','runtime/report.log',save_direct=True,destination=destination))
    assert result['saved_to_destination'] is True
    assert result['destination_verified'] is True
    assert calls[0][1]=='file.receive'
    assert calls[0][2]['explicit_save'] is True
    if destination: assert calls[0][2]['destination']==destination
    else: assert 'destination' not in calls[0][2]
    assert not host._attachment_inbox.for_device('phone')


def _desktop_method(tmp_path,selected):
    content=b'file contents'
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def raise_for_status(self): pass
        def iter_content(self,size): yield content
    calls=[]
    def get(url,**kwargs): calls.append(url);return Response()
    root=NS(after=lambda delay,fn:fn())
    namespace={'Path':Path,'threading':threading,'os':os,'json':json,
               'requests':NS(get=get),
               'QFileDialog':NS(getSaveFileName=lambda *a:(selected,''))}
    method=_method('desktop-companion/companion.py','App','_file_receive',namespace)
    host=NS(root=root,_tls_verify=lambda url:True)
    payload={'explicit_save':True,'name':'report.log','url':'https://server.invalid/download',
             'sha256':hashlib.sha256(content).hexdigest(),'size':len(content)}
    return method,host,payload,content,calls


@pytest.mark.parametrize('folder_mode',[False,True])
def test_desktop_direct_save_uses_requested_file_or_folder(tmp_path,folder_mode):
    method,host,args,content,calls=_desktop_method(tmp_path,'')
    if folder_mode:
        folder=tmp_path/'requested-folder';folder.mkdir();args['destination']=str(folder)
        expected=folder/'report.log'
    else:
        expected=tmp_path/'chosen'/'requested.log';args['destination']=str(expected)
    result=json.loads(method(host,args))
    assert Path(result['saved_to'])==expected
    assert expected.read_bytes()==content
    assert len(calls)==1


def test_desktop_direct_save_without_location_uses_picker(tmp_path):
    expected=tmp_path/'chosen-by-user.log'
    method,host,args,content,calls=_desktop_method(tmp_path,str(expected))
    result=json.loads(method(host,args))
    assert Path(result['saved_to'])==expected
    assert expected.read_bytes()==content


def test_desktop_picker_cancel_does_not_download(tmp_path):
    method,host,args,content,calls=_desktop_method(tmp_path,'')
    with pytest.raises(RuntimeError,match='cancelled'): method(host,args)
    assert not calls


def test_desktop_raw_receive_needs_explicit_save_marker(tmp_path):
    method,host,args,content,calls=_desktop_method(tmp_path,str(tmp_path/'file.log'))
    args.pop('explicit_save')
    with pytest.raises(PermissionError):method(host,args)
    assert not calls


def test_android_picker_is_only_on_explicit_receive_and_downloads_remains_opt_in():
    src=(ROOT/'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text()
    block=src[src.index('if(cap=="file.receive"'):src.index('if(cap=="file.upload"')]
    assert 'a.optString("destination")!="Downloads/Mark"' in block
    assert 'a.optBoolean("explicit_save",false)' in block
    assert block.index('a.optBoolean("explicit_save",false)')<block.index('Intent.ACTION_CREATE_DOCUMENT')
    assert 'DocumentsContract.EXTRA_INITIAL_URI' in block
    assert 'AttachmentTransfer.receive(this,client,a,selected)' in block
