"""OpenAI Realtime WebSocket bridge to Mark's existing session interface.

PCM from companions is 16 kHz; Realtime PCM input/output is 24 kHz. Tool
requests are data returned to Mark's existing guarded executor, never executed
inside this adapter. Session resumption handles are deliberately not emulated.
"""
from __future__ import annotations
import asyncio
import base64
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace as NS
from urllib.parse import urlencode


def _dict(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return vars(value)


def _schema(value):
    if isinstance(value, list):
        return [_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if key == "type":
            out[key] = str(getattr(item, "value", item)).lower()
        elif key in {"properties", "items", "required", "enum", "description", "anyOf",
                     "additionalProperties", "minimum", "maximum", "minItems", "maxItems"}:
            if key == "properties":
                out[key] = {name: _schema(spec) for name, spec in item.items()}
            else:
                out[key] = _schema(item)
    return out


def session_options(config, settings):
    cfg = _dict(config)
    tools = []
    for group in cfg.get("tools") or []:
        for value in _dict(group).get("function_declarations") or []:
            declaration = _dict(value)
            tools.append({"type": "function", "name": declaration["name"],
                          "description": declaration.get("description") or "",
                          "parameters": _schema(declaration.get("parameters_json_schema")
                                                or declaration.get("parameters")
                                                or {"type": "object", "properties": {}})})
    return {"type": "realtime", "output_modalities": ["audio"],
            "instructions": cfg.get("system_instruction") or "",
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000},
                                 "transcription": {"model": settings.get("realtime_transcription_model") or "gpt-4o-mini-transcribe"},
                                 "turn_detection": None},
                      "output": {"format": {"type": "audio/pcm", "rate": 24000},
                                 "voice": settings.get("realtime_voice") or "marin"}},
            "tools": tools, "tool_choice": "auto"}


class PCMResampler:
    """Stateful linear 16→24 kHz conversion; retain phase across chunk edges."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.buffer = []
        self.position = 0.0

    def convert(self, pcm: bytes) -> bytes:
        import numpy as np
        if len(pcm) % 2:
            raise ValueError("PCM16 input must contain complete samples")
        data = np.concatenate((np.asarray(self.buffer, dtype=np.float64),
                               np.frombuffer(pcm, dtype='<i2').astype(np.float64)))
        if len(data) < 2:
            self.buffer = data.tolist()
            return b""
        positions = np.arange(self.position, len(data) - 1, 2 / 3)
        result = np.interp(positions, np.arange(len(data)), data)
        next_position = self.position + len(positions) * (2 / 3)
        consumed = min(int(next_position), len(data) - 1)
        self.buffer = data[consumed:].tolist()
        self.position = next_position - consumed
        return np.rint(result).clip(-32768, 32767).astype('<i2').tobytes()


def _response(*, data=None, sc=None, calls=None):
    return NS(data=data, server_content=sc, tool_call=NS(function_calls=calls) if calls else None,
              session_resumption_update=None)


def _content(**kwargs):
    values = dict(input_transcription=None, output_transcription=None,
                  model_turn=None, turn_complete=False)
    values.update(kwargs)
    return NS(**values)


class RealtimeSession:
    def __init__(self, socket, options):
        self.socket = socket
        self.options = options
        self.resampler = PCMResampler()
        self.audio_bytes = 0
        self.active = False
        self.output_item = None
        self.audio_active = False
        self.seen_calls = set()
        self.pending_calls = set()
        self.allowed_tools = {tool['name'] for tool in options['tools']}

    async def _send(self, event):
        await self.socket.send(json.dumps(event))

    async def configure(self):
        await self._send({"type": "session.update", "session": self.options})
        # Do not enable phone input until the API has accepted our config.
        async with asyncio.timeout(20):
            while True:
                event = json.loads(await self.socket.recv())
                if event.get("type") == "error":
                    raise RuntimeError("OpenAI Realtime rejected session configuration")
                if event.get("type") == "session.updated":
                    return

    async def cancel_response(self):
        if self.active:
            await self._send({"type": "response.cancel"})
            self.active = False
            if self.output_item:
                # Conservatively remove cancelled audio from provider context.
                # The host retains the visible partial transcript separately.
                await self._send({'type': 'conversation.item.truncate',
                                  'item_id': self.output_item, 'content_index': 0,
                                  'audio_end_ms': 0})
                self.output_item = None

    async def send_realtime_input(self, *, activity_start=None, activity_end=None, audio=None):
        if activity_start is not None:
            await self.cancel_response()
            await self._send({"type": "input_audio_buffer.clear"})
            self.audio_bytes = 0
            self.resampler.reset()
            self.audio_active = True
        elif activity_end is not None:
            self.audio_active = False
            if self.audio_bytes >= 4800:  # Realtime requires at least 100 ms.
                await self._send({"type": "input_audio_buffer.commit"})
                await self._send({"type": "response.create"})
                self.active = True
            else:
                await self._send({"type": "input_audio_buffer.clear"})
            self.audio_bytes = 0
        elif audio is not None:
            if not self.audio_active:
                return  # companion silence outside an explicit speech turn
            mime = getattr(audio, "mime_type", "") or ""
            if mime != "audio/pcm;rate=16000":
                raise ValueError("OpenAI Realtime bridge expects PCM16 at 16000 Hz")
            data = self.resampler.convert(audio.data)
            if data:
                await self._send({"type": "input_audio_buffer.append",
                                  "audio": base64.b64encode(data).decode('ascii')})
                self.audio_bytes += len(data)

    async def send_client_content(self, *, turns, turn_complete=True):
        if turn_complete:
            await self.cancel_response()
        if isinstance(turns, dict):
            turns = [turns]
        for turn in turns:
            value = _dict(turn)
            content = []
            role = value.get('role', 'user')
            for part in value.get('parts') or []:
                item = _dict(part)
                if item.get('text'):
                    content.append({'type': 'input_text' if role == 'user' else 'text', 'text': item['text']})
                elif item.get('inline_data'):
                    blob = _dict(item['inline_data'])
                    if blob.get('mime_type') not in {'image/jpeg', 'image/png', 'image/webp'}:
                        raise ValueError('Unsupported image type')
                    encoded = blob['data']
                    if isinstance(encoded, bytes):
                        encoded = base64.b64encode(encoded).decode('ascii')
                    content.append({'type': 'input_image', 'image_url': f"data:{blob['mime_type']};base64,{encoded}"})
            if content:
                await self._send({'type': 'conversation.item.create', 'item': {
                    'type': 'message', 'role': 'assistant' if role == 'model' else role, 'content': content}})
        if turn_complete:
            await self._send({'type': 'response.create'})
            self.active = True

    async def send_tool_response(self, *, function_responses):
        for value in function_responses:
            response = _dict(value)
            call_id = response.get('id')
            if call_id not in self.pending_calls:
                raise ValueError('Unknown Realtime tool response ID')
            await self._send({'type': 'conversation.item.create', 'item': {
                'type': 'function_call_output', 'call_id': call_id,
                'output': json.dumps(response.get('response') or {}, ensure_ascii=False)}})
            self.pending_calls.remove(call_id)
        if not self.pending_calls:
            await self._send({'type': 'response.create'})
            self.active = True

    async def receive(self):
        async for raw in self.socket:
            event = json.loads(raw)
            kind = event.get('type')
            if kind == 'error':
                raise RuntimeError('OpenAI Realtime API error')
            if kind == 'response.created':
                self.active = True
                self.output_item = None
            elif kind == 'response.output_audio.delta':
                self.output_item = event.get('item_id')
                yield _response(data=base64.b64decode(event['delta'], validate=True))
            elif kind == 'response.output_audio_transcript.delta':
                yield _response(sc=_content(output_transcription=NS(text=event['delta'])))
            elif kind == 'conversation.item.input_audio_transcription.completed':
                yield _response(sc=_content(input_transcription=NS(text=event.get('transcript') or '')))
            elif kind == 'response.done':
                self.active = False
                response = event.get('response') or {}
                if response.get('status') == 'failed':
                    raise RuntimeError('OpenAI Realtime response failed')
                calls = []
                if response.get('status') == 'completed':
                    for item in response.get('output') or []:
                        if item.get('type') != 'function_call':
                            continue
                        call_id = item.get('call_id')
                        if not call_id or call_id in self.seen_calls:
                            continue
                        name = item.get('name')
                        if name not in self.allowed_tools:
                            raise ValueError('Realtime requested an undeclared tool')
                        args = json.loads(item.get('arguments') or '{}')
                        if not isinstance(args, dict):
                            raise ValueError('Realtime tool arguments must be an object')
                        self.seen_calls.add(call_id)
                        self.pending_calls.add(call_id)
                        calls.append(NS(id=call_id, name=name, args=args))
                if calls:
                    yield _response(calls=calls)
                else:
                    yield _response(sc=_content(turn_complete=True,
                                                interrupted=response.get('status') == 'cancelled'))
        raise ConnectionError('OpenAI Realtime connection closed')


class RealtimeClient:
    def __init__(self, settings):
        self.settings = dict(settings)
        if not str(self.settings.get('openai_api_key') or '').strip():
            raise ValueError('OpenAI API key required for Realtime')
        self.aio = NS(live=self)

    @asynccontextmanager
    async def connect(self, *, model, config):
        from websockets.asyncio.client import connect
        options = session_options(config, self.settings)
        url = 'wss://api.openai.com/v1/realtime?' + urlencode({'model': model})
        async with connect(url, additional_headers={
            'Authorization': 'Bearer ' + self.settings['openai_api_key']},
            max_size=8 * 1024 * 1024, open_timeout=20) as socket:
            session = RealtimeSession(socket, options)
            await session.configure()
            yield session
