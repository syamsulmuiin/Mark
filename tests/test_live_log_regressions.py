"""Regressions based on playback activity and provider recovery log signatures."""
import ast
import asyncio
from pathlib import Path
import re
import time
from types import SimpleNamespace as NS
import pytest
from core.runtime_errors import Boundary, ErrorAction, classify_error, is_expired_live_session, next_quota_delay
from core.speech_onset import SpeechOnset

ROOT = Path(__file__).resolve().parents[1]


def test_low_level_playback_residual_does_not_open_a_user_turn():
    gate = SpeechOnset()
    frame = {'data': b'\0' * 1024}
    for _ in range(100):
        assert gate.feed(frame, 405, playback=True) == []
    for _ in range(9):
        assert gate.feed(frame, 3000, playback=True) == []
    assert len(gate.feed(frame, 3000, playback=True)) == 10


def test_quiet_speech_still_works_when_assistant_is_idle():
    gate = SpeechOnset()
    frame = {'data': b'\0' * 1024}
    for _ in range(4):
        assert gate.feed(frame, 405) == []
    assert len(gate.feed(frame, 405)) == 5


@pytest.mark.parametrize('message', [
    '1008 None. BidiGenerateContent session not found or expired',
    'session expired', 'session has expired',
])
def test_expiry_is_rollover_not_model_failure(message):
    wrapped = ExceptionGroup('TaskGroup', [RuntimeError(message)])
    assert is_expired_live_session(wrapped)
    assert classify_error(Boundary.LIVE_SESSION, wrapped).action is ErrorAction.SESSION_ROLLOVER


def test_quota_precedes_generic_1011_transport_classification():
    decision = classify_error(Boundary.LIVE_SESSION, '1011 None. You exceeded your current quota, please check your plan and billing details.')
    assert decision.action is ErrorAction.QUOTA_BACKOFF
    assert not decision.traceback
    delay = 0
    observed = []
    for _ in range(6):
        delay = next_quota_delay(delay)
        observed.append(delay)
    assert observed == [60, 120, 240, 300, 300, 300]
    assert classify_error(Boundary.LIVE_SESSION, '1011 Deadline expired before operation could complete.').action is ErrorAction.TRANSPORT_RECONNECT


def runtime_functions():
    tree = ast.parse((ROOT / 'main.py').read_text())
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'_exception_text', '_bounded_exception_text'}]
    namespace = {'re': re}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), 'helpers', 'exec'), namespace)
    return tree, namespace


def test_error_log_redacts_credentials_with_actual_whitespace():
    _, namespace = runtime_functions()
    result = namespace['_bounded_exception_text'](RuntimeError('api_key: private-one token = private-two Authorization: Bearer private-three'))
    assert '[REDACTED]' in result
    assert all(secret not in result for secret in ['private-one', 'private-two', 'private-three'])


@pytest.mark.parametrize('message,clear_handle,delay,previous_delay,age', [
    ('1008 None. BidiGenerateContent session not found or expired', True, 2, 0, 0),
    ('1008 None. BidiGenerateContent session not found or expired', True, 8, 4, 100),
    ('1011 None. You exceeded your current quota, please check your plan and billing details.', False, 60, 0, 0),
])
def test_actual_runtime_handler_clears_expired_handle_and_waits(message, clear_handle, delay, previous_delay, age):
    tree, namespace = runtime_functions()
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    run = next(n for n in cls.body if getattr(n, 'name', '') == 'run')
    handler = next(n for n in ast.walk(run) if isinstance(n, ast.ExceptHandler)
        and isinstance(n.type, ast.Name) and n.type.id == 'BaseException')
    template = ast.parse('async def harness(self):\n while True:\n  try:\n   raise injected\n  except BaseException as e:\n   pass\n')
    template.body[0].body[0].body[0].handlers[0].body = handler.body
    waits, events = [], []

    class StopRetry(BaseException):
        pass

    async def sleep(seconds):
        waits.append(seconds)
        raise StopRetry()

    namespace.update(dict(asyncio=NS(sleep=sleep, Queue=asyncio.Queue), time=time,
        injected=RuntimeError(message), _resumed_with=True, _connected_this_attempt=False, live_model='configured-only',
        _is_reconnect_signal=lambda e: False, _is_transient_transport_error=lambda e: False,
        Boundary=Boundary, ErrorAction=ErrorAction, classify_error=classify_error,
        is_expired_live_session=is_expired_live_session, next_quota_delay=next_quota_delay,
        llm_live=NS(note_model_failure=lambda *a: False),
        _trace_event=lambda event, **kw: events.append((event, kw))))
    exec(compile(ast.fix_missing_locations(template), 'runtime_handler', 'exec'), namespace)
    host = NS(_resume_handle='expired-handle', _session_log=['User: previous request'],
        _conn_backoff=previous_delay, _last_live_connected_at=time.monotonic() - age, _dashboard=None, ui=NS(write_log=lambda text: None))
    host._is_speaking = True
    host.set_speaking = lambda value: setattr(host, '_is_speaking', value)
    with pytest.raises(StopRetry):
        asyncio.run(namespace['harness'](host))
    assert waits == [delay]
    assert not host._is_speaking
    assert host._audio_relay_cursor == 0.0
    assert (host._resume_handle is None) is clear_handle
    assert events[0][0] == 'runtime_error'
    assert events[0][1]['model_fallback'] is False
    if clear_handle:
        assert events[-1][1]['resume_handle_cleared'] is True
    else:
        assert events[-1][1]['reason'] == 'quota'
