import asyncio
import io
import json
import socket
from types import SimpleNamespace
import pytest
from PIL import Image
from core import image_download as download
from core.image_delivery import deliver_image_results


def test_public_resolution_rejects_private_and_mixed_addresses(monkeypatch):
    for addresses in [['127.0.0.1'],['8.8.8.8','10.0.0.1'],['::1']]:
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(None,None,None,None,(ip,443)) for ip in addresses])
        with pytest.raises(ValueError): download.public_target('https://example.org/a.jpg')
    with pytest.raises(ValueError): download.public_target('file:///etc/passwd')
    with pytest.raises(ValueError): download.public_target('https://user:pass@example.org/a')


def test_verified_image_bytes_saved_with_real_format(monkeypatch, tmp_path):
    output = io.BytesIO()
    Image.new('RGB', (2,2), 'red').save(output, format='PNG')
    monkeypatch.setattr(download, 'fetch_image_bytes', lambda url: output.getvalue())
    result = download.save_verified_image('https://example.org/a', tmp_path)
    assert result['image_verified'] is True
    assert result['file_path'].endswith('.png')
    assert result['size'] == len(output.getvalue())
    monkeypatch.setattr(download, 'fetch_image_bytes', lambda url: b'<html>not an image</html>')
    with pytest.raises(Exception): download.save_verified_image('https://example.org/a', tmp_path)


def test_redirect_to_private_host_is_revalidated(monkeypatch):
    seen = []
    def target(url):
        seen.append(url)
        if '127.0.0.1' in url: raise ValueError('non_public_image_host')
        return download.urlsplit(url), '8.8.8.8', 443
    class Connection:
        def __init__(self, *a): pass
        def request(self, *a, **kw): pass
        def getresponse(self): return SimpleNamespace(status=302,getheader=lambda name: 'http://127.0.0.1/a')
        def close(self): pass
    monkeypatch.setattr(download, 'public_target', target)
    monkeypatch.setattr(download, '_PinnedHTTPS', Connection)
    with pytest.raises(ValueError): download.fetch_image_bytes('https://example.org/a')
    assert len(seen) == 2


def test_download_size_limit(monkeypatch):
    class Connection:
        def __init__(self, *a): pass
        def request(self, *a, **kw): pass
        def getresponse(self):
            return SimpleNamespace(status=200,getheader=lambda key: str(download.MAX_BYTES+1))
        def close(self): pass
    monkeypatch.setattr(download, 'public_target', lambda url: (download.urlsplit(url),'8.8.8.8',443))
    monkeypatch.setattr(download, '_PinnedHTTPS', Connection)
    with pytest.raises(ValueError, match='image_too_large'):
        download.fetch_image_bytes('https://example.org/a')


def test_handoff_uses_captured_origin_and_reports_failure():
    calls=[]
    class Dashboard:
        _mesh=SimpleNamespace(get=lambda origin: {'capabilities':['attachment.inbox']})
        async def send_server_file(self, origin, path):
            calls.append((origin,path))
            return {'ok':True,'attachment_id':'image-attachment'}
    payload={'image_artifacts':[{'file_path':'image.png','image_verified':True,'content_verified':True}],'download_failures':[]}
    result=json.loads(asyncio.run(deliver_image_results(payload,Dashboard(),'requesting-phone')))
    assert result['verified'] is True and result['delivered_count'] == 1
    assert calls == [('requesting-phone','image.png')]
    failed=json.loads(asyncio.run(deliver_image_results(payload,None,'requesting-phone')))
    assert failed['status'] == 'WAITING' and failed['verified'] is False


def test_runtime_captures_request_origin_for_images_and_saved_skills():
    import ast
    from pathlib import Path
    tree=ast.parse((Path(__file__).parents[1] / 'main.py').read_text())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_execute_tool')
    assignment=next(n for n in method.body if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='_document_origin' for t in n.targets))
    expression=compile(ast.Expression(assignment.value), 'origin_capture', 'eval')
    host=SimpleNamespace(_dashboard=SimpleNamespace(origin_device_id='requesting-phone'))
    for name,args,expected in [('web_search',{},'requesting-phone'),('skill_manager',{},'requesting-phone'),
                               ('document_editor',{'action':'create'},'requesting-phone'),('save_memory',{},None)]:
        assert eval(expression,{'self':host,'name':name,'args':args}) == expected
