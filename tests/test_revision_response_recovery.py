import ast
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace as NS

from core.approval_feedback import ApprovalSpeechLedger

ROOT = Path(__file__).resolve().parents[1]


def test_fast_completion_replaces_pending_acceptance_and_duplicate_events():
    ledger = ApprovalSpeechLedger()
    assert ledger.offer('one', 'accepted')
    assert ledger.offer('one', 'failed')
    assert not ledger.consume('one','accepted')
    assert ledger.consume('one','failed')
    assert not ledger.offer('one','failed')
    assert not ledger.offer('one','accepted')
    assert not ledger.consume('one','failed')
    assert ledger.offer('two','accepted')
    assert ledger.consume('two','accepted')
    assert ledger.offer('two','succeeded')
    assert ledger.consume('two','succeeded')


def test_actual_voice_sender_coalesces_fast_failure_without_hiding_error():
    tree=ast.parse((ROOT/'main.py').read_text())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_speak_approval_updates')
    namespace={'asyncio':asyncio,'time':time,'_trace_event':lambda *a,**kw:None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'speech','exec'),namespace)
    async def scenario():
        done=asyncio.Event(); spoke=asyncio.Event(); calls=[]
        async def send(**kwargs):
            calls.append(kwargs['turns']['parts'][0]['text']); done.set(); spoke.set()
        ledger=ApprovalSpeechLedger()
        host=NS(_approval_speech_queue=asyncio.Queue(),_approval_speech_ledger=ledger,
            session=NS(send_client_content=send),_is_speaking=False,ui=NS(muted=False),
            _dashboard=NS(active_voice_device='phone',_device_sockets={'phone':object()}),_turn_done_event=done)
        for outcome in ['accepted','failed']:
            ledger.offer('request',outcome)
            host._approval_speech_queue.put_nowait(('phone',outcome,time.monotonic(),'request'))
        task=asyncio.create_task(namespace['_speak_approval_updates'](host))
        await asyncio.wait_for(spoke.wait(),1)
        assert len(calls)==1 and 'action failed' in calls[0]
        assert 'action is starting' not in calls[0]
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    asyncio.run(scenario())


def test_watchdog_does_not_reconnect_during_host_tool_execution():
    tree=ast.parse((ROOT/'main.py').read_text())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_watch_live_stall')
    events=[]
    namespace={'asyncio':asyncio,'time':time,'_trace_event':lambda event,**kw:events.append(event)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'watchdog','exec'),namespace)
    async def scenario():
        reconnect=asyncio.Event()
        host=NS(_pending_voice_turns=[(1,0,0),(2,0,0)],_tool_calls_in_flight=1,
            _live_progress_seq=0,_unanswered_voice_turns=0,_reconnect_event=reconnect)
        task=asyncio.create_task(namespace['_watch_live_stall'](host))
        await asyncio.sleep(.55)
        assert not reconnect.is_set() and not events
        host._tool_calls_in_flight=0
        await asyncio.wait_for(reconnect.wait(),1)
        await task
        assert 'live_stall_reconnect' in events
    asyncio.run(scenario())


def test_docx_outer_fence_is_accepted_but_prose_is_not(tmp_path,monkeypatch):
    from core import document_revisions as rev
    import pytest
    monkeypatch.setattr(rev,'BASE_DIR',tmp_path)
    monkeypatch.setattr(rev,'ARTIFACT_ROOT',tmp_path/'storage/artifacts')
    payload=json.dumps({'blocks':[{'type':'heading','level':1,'text':'Section'},
                                  {'type':'paragraph','text':'Complete body.'}]})
    result=rev.create({'title':'Paper','instruction':'Write complete paper'},lambda _: '```json\n'+payload+'\n```')
    assert result['verified'] and Path(result['file_path']).exists()
    with pytest.raises(ValueError,match='structured document blocks'):
        rev.create({'title':'Paper','instruction':'Write complete paper'},lambda _: 'Here is the result: '+payload)


def test_stale_revision_has_specific_reason_and_inspection_recovery(tmp_path,monkeypatch):
    from actions.document_editor import document_editor
    from core import document_revisions as rev
    monkeypatch.setattr(rev,'BASE_DIR',tmp_path)
    monkeypatch.setattr(rev,'ARTIFACT_ROOT',tmp_path/'storage/artifacts')
    made=rev.create({'title':'Paper','replacement_blocks':[{'type':'heading','level':1,'text':'Section'},
                   {'type':'paragraph','text':'Original body.'}]})
    result=json.loads(document_editor({'action':'revise','file_path':made['file_path'],
        'source_sha256':'old-version','section_heading':'Section','replacement_text':'Updated body.'}))
    assert result['reason']=='source_version_changed'
    assert result['recovery']['operation']=='inspect_before_retry'
    assert 'Do not repeat unchanged revision arguments' in result['instruction']
    assert rev.digest(made['file_path'])==made['sha256']
    event=json.loads((tmp_path/'runtime/interaction.log').read_text().splitlines()[-1])
    assert event['reason']=='source_version_changed'


def test_error_and_progress_do_not_inject_duplicate_assistant_turns():
    tree=ast.parse((ROOT/'main.py').read_text())
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='speak_error')
    namespace={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'error','exec'),namespace)
    logs=[]
    host=NS(ui=NS(write_log=logs.append),speak=lambda _: (_ for _ in ()).throw(AssertionError('duplicate speech')))
    namespace['speak_error'](host,'document_editor','Validation failed')
    assert len(logs)==1 and 'Validation failed' in logs[0]
    heartbeat=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='_tool_progress_heartbeat')
    messages=[n for n in ast.walk(heartbeat) if isinstance(n,ast.Dict)]
    assert all('log' not in [v.value for v in n.values if isinstance(v,ast.Constant)] for n in messages)


def test_revising_a_revision_keeps_unique_compact_name(tmp_path,monkeypatch):
    from core import document_revisions as rev
    monkeypatch.setattr(rev,'BASE_DIR',tmp_path)
    monkeypatch.setattr(rev,'ARTIFACT_ROOT',tmp_path/'storage/artifacts')
    original=rev.create({'title':'Paper','replacement_blocks':[{'type':'heading','level':1,'text':'Section'},
                        {'type':'paragraph','text':'Original body.'}]})
    current=original
    for n in range(3):
        current=rev.revise(current['file_path'],{'source_sha256':current['sha256'],
                           'section_heading':'Section','replacement_text':f'Body version {n}.'})
        assert Path(current['file_path']).name.count('.revised-')==1
    assert Path(original['file_path']).exists()
    assert len(list((tmp_path/'storage/artifacts/documents').glob('*.docx')))==4


def test_document_validation_errors_all_have_payload_free_reason_codes():
    from actions.document_editor import _VALIDATION_REASONS
    tree=ast.parse((ROOT/'core/document_revisions.py').read_text())
    messages=[n.exc.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Raise)
              and isinstance(n.exc,ast.Call) and isinstance(n.exc.func,ast.Name)
              and n.exc.func.id=='ValueError' and n.exc.args and isinstance(n.exc.args[0],ast.Constant)]
    assert set(messages) <= _VALIDATION_REASONS.keys()
