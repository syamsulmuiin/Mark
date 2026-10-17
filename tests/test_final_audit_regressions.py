import ast
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace as NS
from urllib.error import HTTPError
from urllib.request import Request
import pytest
from core import llm_compatible, llm_http

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('endpoint', [
    'http://localhost:123@outside.example/v1/chat/completions',
    'http://127.0.0.1:123@outside.example/v1/chat/completions',
    'http://localhost:bad/v1/chat/completions',
    'http://localhost:123/v1/chat/completions#fragment',
])
def test_local_adapter_rejects_disguised_external_urls(endpoint, monkeypatch):
    monkeypatch.setattr(llm_compatible, 'urlopen', lambda *a, **k: pytest.fail('network called'))
    with pytest.raises(ValueError, match='loopback'):
        llm_compatible.generate_text('ollama_local', 'model', 'hello', endpoint=endpoint)


def test_http_redirect_never_forwards_provider_authorization():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/capture')
            self.end_headers()
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
        def log_message(self, *args): pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(f'http://127.0.0.1:{server.server_port}/provider', data=b'{}',
                          headers={'Authorization': 'Bearer test-secret'})
        with pytest.raises(HTTPError) as error:
            llm_http.urlopen(request, timeout=2)
        assert error.value.code == 302
        assert requests == ['/provider']
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_windows_companion_shell_association_can_launch(monkeypatch):
    path = ROOT / 'desktop-companion/runtime/actions/open_app.py'
    spec = importlib.util.spec_from_file_location('desktop_open_app_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.os, 'startfile', calls.append, raising=False)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    assert module._launch_windows('example-app:')
    assert calls == ['example-app:']


@pytest.mark.parametrize('completed', [True, False])
def test_interrupt_after_buffered_playback_does_not_swallow_next_turn(completed):
    source = ast.parse((ROOT / 'main.py').read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    method = next(n for n in cls.body if getattr(n, 'name', '') == 'interrupt')
    namespace = {'asyncio': asyncio}
    tree = ast.Module(body=[ast.ClassDef(name='Runtime', bases=[], keywords=[], body=[method],
                                        decorator_list=[])], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), 'audit', 'exec'), namespace)
    runtime = namespace['Runtime']()
    runtime._turn_done_event = asyncio.Event()
    if completed: runtime._turn_done_event.set()
    runtime.session = None
    runtime._loop = None
    runtime.audio_in_queue = asyncio.Queue()
    runtime._visemes = NS(reset=lambda: None)
    runtime.ui = NS(write_log=lambda _: None)
    runtime.set_speaking = lambda value: None
    runtime.interrupt()
    assert runtime._interrupted is not completed
    assert runtime._turn_done_event.is_set() is completed
