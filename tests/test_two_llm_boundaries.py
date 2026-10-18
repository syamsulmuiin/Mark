import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from core import gemini, setup_config, chat_router, reasoning, llm_live
from dashboard.server import DashboardServer
from core.llm_openai_realtime import RealtimeSession

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('entry', ['call', 'client'])
def test_unselected_gemini_text_is_rejected_before_key_or_sdk_access(monkeypatch, entry):
    monkeypatch.setattr(setup_config, 'load_config', lambda: {'llm_provider': 'deepseek'})
    monkeypatch.setattr(gemini, 'api_key', lambda **kw: pytest.fail('must not read another provider key'))
    with pytest.raises(RuntimeError, match='selected|configured'):
        getattr(gemini, entry)(*(['test'] if entry == 'call' else []))


def test_selected_text_failure_never_invokes_gemini_or_live(monkeypatch):
    calls = []
    def failed(provider, model, prompt, **kw):
        calls.append((provider, model))
        raise RuntimeError('selected provider unavailable')
    monkeypatch.setattr(chat_router, 'generate_text', failed)
    monkeypatch.setattr(gemini, 'call', lambda *a, **kw: pytest.fail('Gemini fallback'))
    monkeypatch.setattr(llm_live, 'client', lambda *a, **kw: pytest.fail('Live fallback'))
    with pytest.raises(RuntimeError, match='selected provider unavailable'):
        chat_router.generate_chat_text('diagnose', config={'llm_provider': 'deepseek', 'chat_models': 'deepseek-chat', 'deepseek_api_key': 'test'})
    assert calls == [('deepseek', 'deepseek-chat')]


def test_document_helper_follows_selected_text_and_rejects_unsupported_media(monkeypatch):
    from actions import file_processor
    monkeypatch.setattr(reasoning, 'load_config', lambda: {'llm_provider': 'deepseek'})
    calls = []
    monkeypatch.setattr(reasoning, 'generate', lambda text, **kw: calls.append(text) or 'summary')
    assert file_processor._gemini_client().generate_content('actual document text').text == 'summary'
    assert calls == ['actual document text']
    with pytest.raises(ValueError, match='multimodal'):
        file_processor._gemini_client().generate_content([object(), 'image'])
    assert calls == ['actual document text']


def test_web_search_does_not_use_unselected_gemini(monkeypatch):
    from actions import web_search
    monkeypatch.setattr(setup_config, 'load_config', lambda: {'llm_provider': 'deepseek'})
    monkeypatch.setattr(gemini, 'call', lambda *a, **kw: pytest.fail('unselected Gemini search'))
    monkeypatch.setattr(web_search, '_ddg_search', lambda query: [{'title':'Actual result', 'href':'https://example.com', 'body':'evidence'}])
    assert 'Actual result' in web_search._search('test')


def test_clear_audio_is_scoped_to_the_active_authenticated_companion():
    class Socket:
        def __init__(self): self.sent=[]
        async def send_json(self, msg): self.sent.append(msg)
    server = object.__new__(DashboardServer)
    active, other = Socket(), Socket()
    server._active_voice_device = 'active'
    server._device_sockets = {'active':active, 'other':other}
    assert asyncio.run(server.clear_device_audio()) is True
    assert active.sent == [{'type':'audio.clear'}] and other.sent == []
    server._device_sockets.pop('active')
    assert asyncio.run(server.clear_device_audio()) is False
    assert other.sent == []


def test_openai_cancelled_response_is_an_interruption_for_the_host():
    class Socket:
        def __aiter__(self): return self
        async def __anext__(self):
            return json.dumps({'type':'response.done','response':{'status':'cancelled'}})
    async def scenario():
        session = RealtimeSession(Socket(), {'tools':[]})
        event = await anext(session.receive())
        assert event.server_content.interrupted is True
        assert event.server_content.turn_complete is True
    asyncio.run(scenario())


def test_desktop_compatibility_boundary_never_creates_a_provider_client():
    spec = importlib.util.spec_from_file_location('desktop_no_llm', ROOT / 'desktop-companion/runtime/core/gemini.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match='server Text provider'):
        module.call('helper prompt')


def test_only_role_adapters_construct_gemini_clients():
    constructors = []
    for base in ['core','actions','plugins','desktop-companion']:
        for path in (ROOT/base).rglob('*.py'):
            if 'genai.Client(' in path.read_text(): constructors.append(path.relative_to(ROOT).as_posix())
    assert sorted(constructors) == ['core/gemini.py', 'core/llm_live.py']


def test_manual_live_boundary_configuration_is_valid_in_the_real_sdk():
    import ast
    types = pytest.importorskip('google.genai.types')
    tree = ast.parse((ROOT / 'main.py').read_text())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and
                isinstance(n.func, ast.Attribute) and n.func.attr == 'RealtimeInputConfig')
    cfg = eval(compile(ast.Expression(call), 'live-config', 'eval'), {'types':types})
    serialized = types.LiveConnectConfig(realtime_input_config=cfg).model_dump(mode='json', by_alias=True, exclude_none=True)
    assert serialized['realtimeInputConfig']['automaticActivityDetection']['disabled'] is True
    assert serialized['realtimeInputConfig']['activityHandling'] == 'START_OF_ACTIVITY_INTERRUPTS'


def test_new_speech_clears_buffered_playback_after_provider_generation_completed():
    import ast
    tree = ast.parse((ROOT / 'main.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    method = next(n for n in cls.body if getattr(n, 'name', '') == '_send_realtime')
    namespace = {'asyncio':asyncio, 'types':NS(ActivityStart=lambda: 'start'), '_trace_event':lambda *a, **kw: None}
    module = ast.Module(body=[ast.ClassDef(name='Runtime', bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), 'sender', 'exec'), namespace)
    async def scenario():
        runtime = namespace['Runtime']()
        runtime.out_queue = asyncio.Queue()
        runtime._is_speaking = True
        runtime._turn_done_event = asyncio.Event()
        runtime._turn_done_event.set()
        events = []
        runtime.interrupt = lambda: events.append('clear buffered audio')
        runtime._note_voice_activity_start = lambda: None
        async def send(**kw): events.append(kw)
        runtime.session = NS(send_realtime_input=send)
        await runtime.out_queue.put({'activity_start':True})
        task = asyncio.create_task(runtime._send_realtime())
        await asyncio.sleep(0)
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        assert events == ['clear buffered audio', {'activity_start':'start'}]
    asyncio.run(scenario())
