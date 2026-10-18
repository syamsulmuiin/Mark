import asyncio
import base64
import json
from types import SimpleNamespace as NS
import numpy as np
import pytest
from core import llm_live, chat_router, setup_config
from core.llm_openai_realtime import RealtimeSession, PCMResampler, session_options, RealtimeClient


def options():
    return session_options({'system_instruction': 'Mark', 'tools': [{'function_declarations': [
        {'name': 'browser_control', 'parameters': {'type': 'OBJECT', 'properties': {
            'action': {'type': 'STRING'}}, 'required': ['action']}}]}]}, {})


class Socket:
    def __init__(self, events=()):
        self.events = list(events)
        self.sent = []
    async def send(self, raw): self.sent.append(json.loads(raw))
    async def recv(self): return json.dumps(self.events.pop(0))
    def __aiter__(self): return self
    async def __anext__(self):
        if not self.events: raise StopAsyncIteration
        return await self.recv()


def test_realtime_options_preserve_tools_with_json_schema():
    value = options()
    assert value['tools'][0]['parameters']['properties']['action']['type'] == 'string'
    assert value['tools'][0]['parameters']['type'] == 'object'
    assert value['audio']['input']['turn_detection'] is None
    assert value['audio']['output']['format']['rate'] == 24000


def test_resampler_retains_phase_across_chunks():
    pcm = np.arange(-3000, 3000, dtype='<i2').tobytes()
    whole = np.frombuffer(PCMResampler().convert(pcm), dtype='<i2')
    streaming = PCMResampler()
    chunked = np.frombuffer(b''.join(streaming.convert(pcm[i:i+254])
                                   for i in range(0, len(pcm), 254)), dtype='<i2')
    assert len(whole) == len(chunked)
    assert len(whole) in {8998, 8999, 9000}
    assert np.max(np.abs(whole.astype(float) - chunked)) <= 1


def test_realtime_config_handshake_and_manual_audio_turn():
    async def run():
        socket = Socket([{'type': 'session.created'}, {'type': 'session.updated'}])
        session = RealtimeSession(socket, options())
        await session.configure()
        assert socket.sent[0]['type'] == 'session.update'
        await session.send_realtime_input(activity_start=object())
        await session.send_realtime_input(audio=NS(data=b'\x00\x00'*3200,
                                                  mime_type='audio/pcm;rate=16000'))
        await session.send_realtime_input(activity_end=object())
        kinds = [event['type'] for event in socket.sent]
        assert kinds[-2:] == ['input_audio_buffer.commit', 'response.create']
        audio = next(event['audio'] for event in socket.sent if event['type'] == 'input_audio_buffer.append')
        assert 9500 < len(base64.b64decode(audio)) <= 9600
    asyncio.run(run())


def test_short_audio_turn_does_not_commit_or_generate():
    async def run():
        socket = Socket()
        session = RealtimeSession(socket, options())
        await session.send_realtime_input(activity_start=object())
        await session.send_realtime_input(audio=NS(data=b'\0\0'*80, mime_type='audio/pcm;rate=16000'))
        await session.send_realtime_input(activity_end=object())
        assert all(e['type'] not in {'response.create', 'input_audio_buffer.commit'} for e in socket.sent)
    asyncio.run(run())


def test_realtime_audio_transcripts_and_tools_use_mark_session_interface():
    async def run():
        events = [{'type': 'response.output_audio.delta', 'delta': base64.b64encode(b'pcm').decode()},
                  {'type': 'response.output_audio_transcript.delta', 'delta': 'Halo'},
                  {'type': 'conversation.item.input_audio_transcription.completed', 'transcript': 'Buka'},
                  {'type': 'response.done', 'response': {'status': 'completed', 'output': [
                      {'type': 'function_call', 'call_id': 'call_1', 'name': 'browser_control',
                       'arguments': '{"action":"open"}'}]}}]
        socket = Socket(events)
        session = RealtimeSession(socket, options())
        responses = []
        async for response in session.receive():
            responses.append(response)
            if response.tool_call: break
        assert responses[0].data == b'pcm'
        assert responses[1].server_content.output_transcription.text == 'Halo'
        assert responses[2].server_content.input_transcription.text == 'Buka'
        call = responses[3].tool_call.function_calls[0]
        assert (call.id, call.name, call.args) == ('call_1', 'browser_control', {'action': 'open'})
        # No tool executes in the adapter. The host supplies the guarded result.
        await session.send_tool_response(function_responses=[NS(id='call_1', response={'approval_required': True})])
        assert json.loads(socket.sent[0]['item']['output']) == {'approval_required': True}
        assert socket.sent[0]['item']['call_id'] == 'call_1'
        assert socket.sent[1] == {'type': 'response.create'}
        with pytest.raises(ValueError):
            await session.send_tool_response(function_responses=[NS(id='unknown', response={})])
    asyncio.run(run())


def test_failed_realtime_session_does_not_fallback():
    async def run():
        session = RealtimeSession(Socket([{'type': 'error', 'error': {'message': 'secret'}}]), options())
        with pytest.raises(RuntimeError, match='API error') as error:
            async for _ in session.receive(): pass
        assert 'secret' not in str(error.value)
    asyncio.run(run())


def test_realtime_client_factory_and_model_are_independent_from_gemini():
    cfg = {'live_provider': 'openai_realtime', 'openai_api_key': 'test',
           'realtime_model': 'my-realtime-model', 'live_models': 'gemini-only'}
    assert isinstance(llm_live.client(cfg), RealtimeClient)
    assert llm_live.model(cfg) == 'my-realtime-model'
    assert llm_live.note_model_failure('my-realtime-model', '429', cfg) is False
    with pytest.raises(ValueError):
        llm_live.client({'live_provider': 'openai_realtime'})


def test_setup_saves_openai_voice_without_overwriting_gemini_models(tmp_path, monkeypatch):
    path = tmp_path / 'keys.json'
    path.write_text(json.dumps({'gemini_api_key': 'gemini-key', 'live_models': 'gemini-live'}))
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    replies = iter(['2', 'my-text-model', '2', 'my-realtime-model'])
    monkeypatch.setattr('builtins.input', lambda _: next(replies))
    prompts = []
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda p: prompts.append(p) or 'openai-key')
    assert setup_config.interactive_llm_setup()
    saved = json.loads(path.read_text())
    assert saved['live_provider'] == 'openai_realtime'
    assert saved['realtime_model'] == 'my-realtime-model'
    assert saved['live_models'] == 'gemini-live'
    assert saved['gemini_api_key'] == 'gemini-key'
    assert saved['openai_api_key'] == 'openai-key'
    assert len(prompts) == 1


def test_codex_router_does_not_require_api_key_or_call_other_adapters(monkeypatch):
    calls = []
    monkeypatch.setattr(chat_router, 'generate_codex_text', lambda *a, **k: calls.append((a, k)) or 'OK')
    monkeypatch.setattr(chat_router, 'generate_text', lambda *a, **k: pytest.fail('wrong adapter'))
    assert chat_router.generate_chat_text('hello', config={'llm_provider': 'openai_codex',
                                                          'chat_models': 'my-model'}) == 'OK'
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "my-model" and kwargs == {"timeout": 120.0}
    assert args[1].startswith("[HOST MODEL IDENTITY]") and args[1].endswith("\n\nhello")


def test_realtime_waits_for_all_tool_results_before_continuing():
    async def run():
        socket = Socket()
        session = RealtimeSession(socket, options())
        session.pending_calls = {'a', 'b'}
        await session.send_tool_response(function_responses=[NS(id='a', response={'ok': True})])
        assert all(event['type'] != 'response.create' for event in socket.sent)
        await session.send_tool_response(function_responses=[NS(id='b', response={'ok': False})])
        assert socket.sent[-1]['type'] == 'response.create'
    asyncio.run(run())


@pytest.mark.parametrize('name,arguments', [('unknown', '{}'), ('browser_control', '[]'),
                                           ('browser_control', 'malformed')])
def test_realtime_rejects_invalid_tool_calls(name, arguments):
    async def run():
        socket = Socket([{'type': 'response.done', 'response': {'status': 'completed', 'output': [
            {'type': 'function_call', 'call_id': 'a', 'name': name, 'arguments': arguments}]}}])
        session = RealtimeSession(socket, options())
        with pytest.raises(ValueError):
            async for _ in session.receive(): pass
    asyncio.run(run())


def test_realtime_only_setup_does_not_require_gemini_key(tmp_path, monkeypatch):
    path = tmp_path / 'keys.json'
    monkeypatch.setattr(setup_config, 'CONFIG_FILE', path)
    replies = iter(['2', 'text-model', '2', 'voice-model'])
    monkeypatch.setattr('builtins.input', lambda _: next(replies))
    monkeypatch.setattr(setup_config.getpass, 'getpass', lambda _: 'openai-key')
    assert setup_config.interactive_llm_setup()
    assert setup_config.configured()
    assert 'gemini_api_key' not in json.loads(path.read_text())


def test_realtime_connect_uses_official_endpoint_and_waits_for_ack(monkeypatch):
    import websockets.asyncio.client
    captured = {}
    socket = Socket([{'type': 'session.created'}, {'type': 'session.updated'}])
    class Connection:
        async def __aenter__(self): return socket
        async def __aexit__(self, *args): pass
    def connect(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Connection()
    monkeypatch.setattr(websockets.asyncio.client, 'connect', connect)
    async def run():
        client = RealtimeClient({'openai_api_key': 'test-key'})
        async with client.aio.live.connect(model='voice-model', config={'tools': []}) as session:
            assert isinstance(session, RealtimeSession)
            assert socket.sent[0]['type'] == 'session.update'
            assert not socket.events
    asyncio.run(run())
    assert captured['url'] == 'wss://api.openai.com/v1/realtime?model=voice-model'
    assert captured['additional_headers'] == {'Authorization': 'Bearer test-key'}
