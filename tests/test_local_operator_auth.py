from types import SimpleNamespace as NS
import json
import stat
import urllib.request

from core.local_api_auth import authorized_local_request, local_headers, local_token


def request(headers,host='127.0.0.1'):
    return NS(headers={k.lower():v for k,v in headers.items()},client=NS(host=host))


def test_proxy_loopback_and_legacy_header_do_not_grant_operator_access(tmp_path):
    token=local_token(tmp_path,create=True)
    assert not authorized_local_request(request({'X-Jarvis-Local':'1','CF-Connecting-IP':'8.8.8.8'}),token)
    assert not authorized_local_request(request({'X-Jarvis-Local':'1','X-Mark-Local-Token':'wrong'}),token)
    assert authorized_local_request(request(local_headers(tmp_path)),token)
    assert not authorized_local_request(request(local_headers(tmp_path),host='8.8.8.8'),token)
    assert local_token(tmp_path,create=True)==token
    assert stat.S_IMODE((tmp_path/'devices/local_api.token').stat().st_mode)==0o600


def test_cli_health_request_supplies_the_owner_credential(tmp_path,monkeypatch):
    from core import server_lifecycle as lifecycle
    token=local_token(tmp_path,create=True)
    monkeypatch.setattr(lifecycle,'BASE_DIR',tmp_path)
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self):return json.dumps({'service':'Mark','status':'ready','pid':1234}).encode()
    def urlopen(req,**kwargs):
        headers={k.lower():v for k,v in req.header_items()}
        assert headers['x-mark-local-token']==token
        return Response()
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    assert lifecycle._local_server_identity()==1234


def test_actual_operator_routes_require_token_before_accessing_mesh(tmp_path):
    import ast
    import asyncio
    import os
    from pathlib import Path
    from core.device_mesh import DeviceMesh
    token=local_token(tmp_path,create=True)
    tree=ast.parse((Path(__file__).resolve().parents[1]/'dashboard/server.py').read_text())
    routes=[n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name in
            {'local_health','local_pairing_pending','local_pairing_new'}]
    for node in routes:node.decorator_list=[]
    ns={'self':NS(_local_api_token=token,_mesh=DeviceMesh(tmp_path)),
        'Request':object,'JSONResponse':lambda data,status_code=200:NS(data=data,status_code=status_code),'os':os}
    exec(compile(ast.fix_missing_locations(ast.Module(body=routes,type_ignores=[])),'local routes','exec'),ns)
    for name in ['local_health','local_pairing_pending','local_pairing_new']:
        denied=asyncio.run(ns[name](request({'X-Jarvis-Local':'1'})))
        assert denied.status_code==403
    allowed=asyncio.run(ns['local_health'](request(local_headers(tmp_path))))
    assert allowed.status_code==200 and allowed.data['pid']==os.getpid()
