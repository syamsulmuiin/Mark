import ast
import asyncio
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
from core import confirm
from core.approval_feedback import speech_instruction


def prepare(monkeypatch):
    timers = []
    class Timer:
        def __init__(self, delay, callback):
            self.callback = callback
            self.cancelled = False
            timers.append(self)
        def start(self): pass
        def cancel(self): self.cancelled = True
    monkeypatch.setattr(confirm, '_pending', None)
    monkeypatch.setattr(confirm.threading, 'Timer', Timer)
    return timers


def test_permission_ack_precedes_execution_and_completion(monkeypatch):
    prepare(monkeypatch)
    events = []
    finished = threading.Event()
    confirm.bind(lambda *a: None, lambda: None,
        on_decision=lambda request, outcome: events.append(outcome),
        on_result=lambda *args: (events.append('succeeded' if args[3] else 'failed'), finished.set()))
    confirm.request('voice-test', 'Private action', 'secret arguments', lambda: events.append('execute') or 'done')
    request = confirm.pending_request()['request_id']
    confirm.resolve(True, expected_request_id=request)
    assert finished.wait(1)
    assert events == ['accepted', 'execute', 'succeeded']
    confirm.resolve(True, expected_request_id=request)
    assert events == ['accepted', 'execute', 'succeeded']
    confirm.bind(lambda *a: None, lambda: None)


def test_server_timer_reports_expiry_without_a_client_reply(monkeypatch):
    timers = prepare(monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(confirm.time, 'monotonic', lambda: clock[0])
    decisions, results, ran = [], [], []
    confirm.bind(lambda *a: None, lambda: None,
        on_decision=lambda request, outcome: decisions.append(outcome),
        on_result=lambda *args: results.append(args[-1]))
    confirm.request('expiry-test', 'Action', '', lambda: ran.append(True))
    request = confirm.pending_request()['request_id']
    clock[0] += confirm.TIMEOUT_SECONDS
    timers[0].callback()
    confirm.resolve(True, expected_request_id=request)
    assert decisions == ['expired'] and results == ['expired'] and not ran
    assert timers[0].cancelled
    confirm.bind(lambda *a: None, lambda: None)


def test_rejection_has_one_decision_and_no_execution(monkeypatch):
    prepare(monkeypatch)
    events = []
    confirm.bind(lambda *a: None, lambda: None,
        on_decision=lambda request, outcome: events.append(outcome))
    confirm.request('reject-test', 'Action', '', lambda: events.append('execute'))
    confirm.resolve(False, expected_request_id=confirm.pending_request()['request_id'])
    assert events == ['rejected']
    confirm.bind(lambda *a: None, lambda: None)


def test_failed_execution_never_becomes_success_feedback(monkeypatch):
    prepare(monkeypatch)
    events = []
    finished = threading.Event()
    confirm.bind(lambda *a: None, lambda: None,
        on_result=lambda *args: (events.append((args[3], args[4])), finished.set()))
    confirm.request('fail-test', 'Action', '', lambda: (_ for _ in ()).throw(RuntimeError('private error')))
    confirm.resolve(True, expected_request_id=confirm.pending_request()['request_id'])
    assert finished.wait(1)
    assert events == [(False, 'failed')]
    assert 'Do not claim success' in speech_instruction('failed')
    confirm.bind(lambda *a: None, lambda: None)


def test_voice_queue_waits_for_owner_and_sends_decision_then_result():
    source = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    method = next(n for n in cls.body if getattr(n, 'name', '') == '_speak_approval_updates')
    namespace = dict(asyncio=asyncio, time=time, _trace_event=lambda *a, **kw: None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), 'feedback', 'exec'), namespace)
    async def scenario():
        calls = []
        received = asyncio.Event()
        done = asyncio.Event()
        async def send(**kw):
            calls.append(kw['turns']['parts'][0]['text'])
            done.set()
            if len(calls) == 2: received.set()
        dashboard = NS(active_voice_device='other', _device_sockets={'phone': object()})
        host = NS(_approval_speech_queue=asyncio.Queue(), session=NS(send_client_content=send),
            _is_speaking=False, ui=NS(muted=False), _dashboard=dashboard, _turn_done_event=done)
        await host._approval_speech_queue.put(('phone', 'accepted', time.monotonic()))
        await host._approval_speech_queue.put(('phone', 'succeeded', time.monotonic()))
        task = asyncio.create_task(namespace['_speak_approval_updates'](host))
        await asyncio.sleep(0.02)
        assert not calls and dashboard.active_voice_device == 'other'
        dashboard.active_voice_device = 'phone'
        await asyncio.wait_for(received.wait(), 1)
        assert 'Thank the user' in calls[0]
        assert 'completed successfully' in calls[1]
        assert all('Do not call tools' in text for text in calls)
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    asyncio.run(scenario())


def test_old_expiry_timer_cannot_resolve_a_replacement_request(monkeypatch):
    timers = prepare(monkeypatch)
    decisions = []
    confirm.bind(lambda *a: None, lambda: None,
        on_decision=lambda request, outcome: decisions.append(outcome))
    confirm.request('timer-one', 'First', '', lambda: 'done')
    first = confirm.pending_request()['request_id']
    confirm.resolve(False, expected_request_id=first)
    confirm.request('timer-two', 'Second', '', lambda: 'done')
    second = confirm.pending_request()['request_id']
    timers[0].callback()
    assert confirm.pending_request()['request_id'] == second
    assert decisions == ['rejected']
    confirm.resolve(False, expected_request_id=second)
    confirm.bind(lambda *a: None, lambda: None)


def test_replacing_expired_gate_still_reports_its_expiry(monkeypatch):
    timers = prepare(monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(confirm.time, 'monotonic', lambda: clock[0])
    decisions = []
    confirm.bind(lambda *a: None, lambda: None,
        on_decision=lambda request, outcome: decisions.append(outcome))
    confirm.request('delayed-one', 'First', '', lambda: 'done')
    clock[0] += confirm.TIMEOUT_SECONDS + 1
    confirm.request('delayed-two', 'Second', '', lambda: 'done')
    assert decisions == ['expired'] and timers[0].cancelled
    assert confirm.pending_title() == 'Second'
    timers[0].callback()
    assert decisions == ['expired']
    confirm.resolve(False)
    confirm.bind(lambda *a: None, lambda: None)
