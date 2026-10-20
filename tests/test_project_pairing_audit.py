"""Actual desktop pairing methods against the server mesh without Qt/hardware."""
import ast
import json
import os
import secrets
import socket
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from core.device_mesh import DeviceMesh

ROOT=Path(__file__).resolve().parents[1]


def desktop_namespace(tmp_path):
    tree=ast.parse((ROOT/'desktop-companion/companion.py').read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
        {'b64','unb64','load','save','identity','priv','verify'}]
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='App')
    functions += [n for n in cls.body if getattr(n,'name','')=='_pair_worker']
    ns=dict(json=json,os=os,secrets=secrets,socket=socket,threading=threading,time=time,uuid=uuid,
        STATE=tmp_path/'state.json',_STATE_LOCK=threading.RLock(),
        Ed25519PrivateKey=Ed25519PrivateKey,Ed25519PublicKey=Ed25519PublicKey,serialization=serialization,
        PUBLIC_BASE_URL='https://mark.example',NATIVE_CAPABILITIES=['jarvis.command','attachment.inbox'])
    import base64
    ns['base64']=base64
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),'desktop','exec'),ns)
    return ns


@pytest.mark.parametrize('failure',[None,'server_changed','disk_full'])
def test_desktop_request_operator_code_claim_matches_actual_server(tmp_path,failure):
    ns=desktop_namespace(tmp_path)
    st=ns['identity']({})
    initial=dict(st)
    mesh=DeviceMesh(tmp_path/'server')
    events=[]
    def post(url,json,**kwargs):
        assert kwargs['verify'] is True
        if url.endswith('/api/pairing/request'):
            data=mesh.create_pairing_request(json['peer'])
        else:
            assert url.endswith('/api/pairing/claim')
            device=mesh.claim_pairing_request(json['pairing_id'],json['code'],json['signature'],json['capabilities'])
            data={'ok':True,'local':mesh.public_identity(),'device':device}
            if failure=='server_changed': data['local']={**data['local'],'device_id':'wrong-server'}
        return NS(ok=True,status_code=200,json=lambda:data,raise_for_status=lambda:None)
    ns['requests']=NS(post=post)
    host=NS(st=st,_pending_pairing=None,_tls_verify=lambda _:True,
        root=NS(after=lambda _,fn:fn()),_pair_requested=lambda:events.append('requested'),
        _paired=lambda:events.append('paired'),_pair_failed=lambda msg:events.append('failed'),
        note=lambda _:None,fault=lambda *a:None)
    ns['_pair_worker'](host,'')
    assert events==['requested'] and host.st==initial
    code=mesh.issue_pairing_code(host._pending_pairing['pairing_id'])['code']
    if failure=='disk_full':
        ns['save']=lambda _: (_ for _ in ()).throw(OSError('disk full'))
    ns['_pair_worker'](host,code)
    if failure:
        assert events[-1]=='failed' and host.st==initial
    else:
        assert events[-1]=='paired' and host.st['server_key']==mesh.public_key
        assert mesh.authorized(st['device_id'],'attachment.inbox')
        assert json.loads(ns['STATE'].read_text())['paired'] is True


@pytest.mark.parametrize('raw',['{broken','null','[]'])
def test_corrupt_desktop_state_never_silently_resets(tmp_path,raw):
    ns=desktop_namespace(tmp_path); ns['STATE'].write_text(raw)
    with pytest.raises(RuntimeError): ns['load']()
    assert ns['STATE'].read_text()==raw


@pytest.mark.parametrize('state',[{'paired':True},{'device_id':'desktop'},{'private_key':'bad','public_key':'bad'}])
def test_partial_desktop_identity_never_replaced(tmp_path,state):
    ns=desktop_namespace(tmp_path)
    with pytest.raises(RuntimeError): ns['identity'](state)
    assert not ns['STATE'].exists()


def test_failed_desktop_atomic_save_preserves_identity(tmp_path,monkeypatch):
    ns=desktop_namespace(tmp_path); original=ns['identity']({}); raw=ns['STATE'].read_bytes()
    monkeypatch.setattr(os,'replace',lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError): ns['save']({**original,'paired':True})
    assert ns['STATE'].read_bytes()==raw
    assert not list(tmp_path.glob('*.tmp'))


def signed_request(mesh):
    key=Ed25519PrivateKey.generate()
    peer={'device_id':'desktop','name':'Desktop','public_key':DeviceMesh._b64(key.public_key().public_bytes_raw())}
    request=mesh.create_pairing_request(peer)
    code=mesh.issue_pairing_code(request['pairing_id'])['code']
    signature=DeviceMesh._b64(key.sign(f"{request['pairing_id']}:{code}:{request['nonce']}".encode()))
    return request['pairing_id'],code,signature


def test_failed_trust_persistence_does_not_authorize_device_or_consume_code(tmp_path,monkeypatch):
    mesh=DeviceMesh(tmp_path); args=signed_request(mesh); atomic=mesh._atomic
    monkeypatch.setattr(mesh,'_atomic',lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):mesh.claim_pairing_request(*args)
    assert not mesh.authorized('desktop','jarvis.command')
    monkeypatch.setattr(mesh,'_atomic',atomic)
    mesh.claim_pairing_request(*args)
    assert mesh.authorized('desktop','jarvis.command')


def test_failed_capability_save_does_not_grant_in_memory_permission(tmp_path,monkeypatch):
    mesh=DeviceMesh(tmp_path); mesh.claim_pairing_request(*signed_request(mesh))
    monkeypatch.setattr(mesh,'_atomic',lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):mesh.set_capabilities('desktop',['new.permission'])
    assert not mesh.authorized('desktop','new.permission')
    assert mesh.authorized('desktop','jarvis.command')


def test_pairing_queue_is_bounded_and_prunes_expired(tmp_path,monkeypatch):
    mesh=DeviceMesh(tmp_path)
    key=Ed25519PrivateKey.generate()
    peer={'device_id':'desktop','public_key':DeviceMesh._b64(key.public_key().public_bytes_raw())}
    for _ in range(128):mesh.create_pairing_request(peer,ttl=10)
    with pytest.raises(ValueError,match='queue full'):mesh.create_pairing_request(peer)
    future=time.time()+20
    monkeypatch.setattr(time,'time',lambda:future)
    mesh.create_pairing_request(peer)
    assert len(mesh._pending)==1


def test_android_pending_pairing_does_not_replace_active_server_trust():
    source=(ROOT/'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text()
    request=source.split('private fun requestPairing()',1)[1].split('private fun pairWithCode',1)[0]
    assert '.putString("pending_server_key"' in request
    assert '.putString("server_key"' not in request and '.putString("server_id"' not in request
    claim=source.split('private fun pairWithCode',1)[1].split('@Synchronized private fun connect',1)[0]
    assert 'local.getString("public_key") != pendingKey' in claim
    assert claim.index('local.getString("public_key") != pendingKey') < claim.index('.putString("server_key", pendingKey)')


def test_existing_empty_state_is_not_a_fresh_installation(tmp_path):
    ns=desktop_namespace(tmp_path)
    ns['STATE'].write_text('{}')
    with pytest.raises(RuntimeError,match='no identity'):
        ns['identity'](ns['load']())
    assert ns['STATE'].read_text()=='{}'
