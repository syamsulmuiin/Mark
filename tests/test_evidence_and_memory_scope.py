"""Real readback adapters, final-condition checks and scoped memory retrieval."""
import ast
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.agent_memory import AgentMemory
from core.autonomy_engine import AutonomousCoordinator, state_verifier
from core.autonomy_state import GoalStore, WorldState
from core.capability_registry import Capability, CapabilityRegistry
from core.host_observations import HostObserver


def setup(tmp_path, executor):
    caps = CapabilityRegistry()
    caps.register(Capability('create'))
    store, world = GoalStore(tmp_path), WorldState(tmp_path)
    observer = HostObserver(tmp_path, caps, lambda *args: None)
    coordinator = AutonomousCoordinator(store, world, caps, executor, state_verifier, observer=observer)
    return coordinator, world


def file_step(name, path):
    return {'id': name, 'capability': 'create', 'verify': {'section': name, 'equals': True,
            'probe': {'type': 'server_file', 'path': path, 'field': 'exists'}}}


def test_real_file_readback_completes_goal_and_records_hash(tmp_path):
    path = tmp_path / 'storage' / 'report.txt'
    path.parent.mkdir()
    def execute(*args):
        path.write_text('actual report')
        return {'status': 'SUCCESS'}
    coordinator, world = setup(tmp_path, execute)
    goal = coordinator.create_goal('Create report', [file_step('report', 'storage/report.txt')])
    result = coordinator.advance(goal['goal_id'])
    assert result['status'] == 'GOAL_ACHIEVED'
    evidence = world.data['observed']['report']['evidence']
    assert evidence['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert evidence['size'] == path.stat().st_size


def test_claimed_success_without_file_cannot_complete(tmp_path):
    coordinator, world = setup(tmp_path, lambda *args: {'status': 'SUCCESS', 'verified': True})
    goal = coordinator.create_goal('Create report', [file_step('report', 'storage/missing.txt')])
    assert coordinator.advance(goal['goal_id'])['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'


def test_final_verification_detects_earlier_output_removed_by_later_step(tmp_path):
    folder = tmp_path / 'storage'
    folder.mkdir()
    first, second = folder / 'first.txt', folder / 'second.txt'
    calls = []
    def execute(cap, args, goal):
        calls.append(1)
        if len(calls) == 1:
            first.write_text('first')
        else:
            first.unlink()
            second.write_text('second')
        return {'status': 'SUCCESS'}
    coordinator, world = setup(tmp_path, execute)
    steps = [file_step('first', 'storage/first.txt'), file_step('second', 'storage/second.txt')]
    steps[1]['depends_on'] = ['first']
    goal = coordinator.create_goal('Create both files', steps)
    assert coordinator.advance(goal['goal_id'])['status'] == 'RUNNING'
    result = coordinator.advance(goal['goal_id'])
    assert result['completed_steps'] == ['first', 'second']
    assert result['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    first.write_text('restored')
    assert coordinator.advance(goal['goal_id'])['status'] == 'GOAL_ACHIEVED'
    assert len(calls) == 2


def test_additional_goal_condition_must_hold_after_all_steps(tmp_path):
    path = tmp_path / 'storage' / 'report.txt'
    path.parent.mkdir()
    path.write_text('report')
    coordinator, world = setup(tmp_path, lambda *args: {'status': 'SUCCESS'})
    check = {'section': 'approval_recorded', 'equals': True}
    goal = coordinator.create_goal('Report and independent review',
        [file_step('report', 'storage/report.txt')], completion_checks=[check])
    assert coordinator.advance(goal['goal_id'])['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    world.update_observed('approval_recorded', True, 'host review record')
    assert coordinator.advance(goal['goal_id'])['status'] == 'GOAL_ACHIEVED'


def test_host_probe_rejects_source_and_symlink_escape(tmp_path):
    observer = HostObserver(tmp_path, CapabilityRegistry(), None)
    outside = tmp_path / 'source.py'
    outside.write_text('source')
    (tmp_path / 'storage').mkdir()
    (tmp_path / 'storage/link').symlink_to(outside)
    for path in ('source.py', 'storage/link'):
        with pytest.raises(PermissionError):
            observer(file_step('file', path), None, WorldState(tmp_path), {})


def test_companion_inspection_uses_exact_target_permission_and_readback(tmp_path):
    caps = CapabilityRegistry()
    caps.register(Capability('app.inspect', device_id='phone', source='companion', permissions=('app.inspect',)))
    calls = []
    def inspect(cap, args, goal):
        calls.append((cap.device_id, cap.name))
        return {'ok': True, 'status': 'SUCCESS', 'verified': True, 'result': 'com.example.app',
                'evidence': {'active_package': 'com.example.app'}, 'call_id': 'host-call'}
    observer = HostObserver(tmp_path, caps, inspect)
    step = {'id': 'open', 'verify': {'section': 'foreground', 'probe': {
        'type': 'companion', 'capability': 'app.inspect', 'field': 'evidence.active_package'}}}
    goal = {'active_step': {'execution_target': 'phone'},
            'execution_context': {'granted_permissions': ['app.inspect']}}
    world = WorldState(tmp_path)
    assert observer(step, None, world, goal)
    assert world.observed('foreground') == 'com.example.app'
    assert calls == [('phone', 'app.inspect')]
    goal['active_step']['execution_target'] = 'another-phone'
    with pytest.raises(PermissionError):
        observer(step, None, world, goal)
    assert len(calls) == 1


def test_mutating_capability_cannot_be_used_as_probe(tmp_path):
    observer = HostObserver(tmp_path, CapabilityRegistry(), lambda *args: pytest.fail('side effect'))
    with pytest.raises(ValueError, match='read_only'):
        observer({'verify': {'section': 'app', 'probe': {'type': 'companion', 'capability': 'app.launch'}}},
                 None, WorldState(tmp_path), {})


@pytest.mark.parametrize('change', ['device', 'socket', 'capability', 'current_socket', 'none'])
def test_reply_binding_rejects_other_device_socket_and_capability(change):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'dashboard/server.py').read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                  and node.name == 'accept_capability_reply')
    ns = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<reply binding>', 'exec'), ns)
    socket, other, received = object(), object(), []
    future = SimpleNamespace(done=lambda: bool(received), set_result=received.append)
    host = SimpleNamespace(_device_pending_targets={'call': ('phone', socket, 'app.inspect')},
        _device_pending_calls={'call': future}, _device_sockets={'phone': socket})
    msg = {'call_id': 'call', 'capability': 'wrong' if change == 'capability' else 'app.inspect'}
    if change == 'current_socket':
        host._device_sockets['phone'] = other
    result = ns['accept_capability_reply'](host, 'other' if change == 'device' else 'phone',
        other if change == 'socket' else socket, msg)
    assert result is (change == 'none')
    assert len(received) == (1 if change == 'none' else 0)
    if received:
        assert ns['accept_capability_reply'](host, 'phone', socket, msg) is False


def verified(memory, *, environment=None, commit='', created=None):
    row = memory.add('procedural', 'calc knowledge', 'test evidence', environment=environment, repository_commit=commit)
    row = memory.promote(row['id'], 'VERIFIED', 'independent tests')
    if created:
        row['validated_at'] = created
        memory._write(row)
    return row


def test_automatic_memory_scope_excludes_old_foreign_and_unknown_records(tmp_path):
    memory = AgentMemory(tmp_path)
    environment = {'os': 'Linux', 'python': '3.12'}
    now = datetime.now(timezone.utc)
    keep = verified(memory, environment=environment, commit='current')
    verified(memory, environment={'os': 'Windows'}, commit='current')
    verified(memory, environment=environment, commit='previous')
    verified(memory)
    verified(memory, environment=environment, commit='current', created=(now-timedelta(days=31)).isoformat())
    verified(memory, environment=environment, commit='current', created=(now+timedelta(days=1)).isoformat())
    rows = memory.search('calc', verified_only=True, environment=environment, repository_commit='current',
                         max_age_days=30, now=now+timedelta(seconds=1), strict_scope=True)
    assert [row['id'] for row in rows] == [keep['id']]
    assert len(memory.search('calc')) == 6


def test_contradicted_memory_is_not_automatically_reused(tmp_path):
    memory = AgentMemory(tmp_path)
    row = verified(memory, environment={'os': 'Linux'}, commit='current')
    memory.contradiction(row['id'], 'new evidence disagrees')
    assert memory.search('calc', verified_only=True, environment={'os': 'Linux'},
                         repository_commit='current', max_age_days=30, strict_scope=True) == []
    assert memory.get(row['id'])['history'][-1]['status'] == 'CONFLICT'


def test_explicit_final_conditions_allow_transient_intermediate_state(tmp_path):
    store, world, caps = GoalStore(tmp_path), WorldState(tmp_path), CapabilityRegistry()
    caps.register(Capability('app'))
    def execute(cap, args, goal):
        world.update_observed('app', args['state'], 'host process readback')
        return {'status': 'SUCCESS'}
    coordinator = AutonomousCoordinator(store, world, caps, execute, state_verifier)
    plan = [{'id': state, 'capability': 'app', 'inputs': {'state': state},
             'verify': {'section': 'app', 'equals': state}} for state in ('opened', 'closed')]
    plan[1]['depends_on'] = ['opened']
    goal = coordinator.create_goal('Open and then close app', plan,
        completion_checks=[{'section': 'app', 'equals': 'closed'}])
    assert coordinator.advance(goal['goal_id'])['status'] == 'RUNNING'
    assert coordinator.advance(goal['goal_id'])['status'] == 'GOAL_ACHIEVED'


def test_changed_condition_needs_real_baseline_and_actual_change(tmp_path):
    store, world, caps = GoalStore(tmp_path), WorldState(tmp_path), CapabilityRegistry()
    caps.register(Capability('edit'))
    world.update_observed('document', 'original', 'initial readback')
    coordinator = AutonomousCoordinator(store, world, caps, lambda *args: {'status': 'SUCCESS'}, state_verifier)
    goal = coordinator.create_goal('Change document', [{'id': 'edit', 'capability': 'edit',
        'verify': {'section': 'document', 'changed': True}}])
    assert coordinator.advance(goal['goal_id'])['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    world.update_observed('document', 'revised', 'actual revision readback')
    assert coordinator.advance(goal['goal_id'])['status'] == 'GOAL_ACHIEVED'
    assert state_verifier({'verify': {'section': 'document', 'changed': True}},
        {'status': 'SUCCESS'}, world, {})['reason'] == 'verification_baseline_required'


def test_failed_readback_cannot_reuse_old_success_observation(tmp_path):
    coordinator, world = setup(tmp_path, lambda *args: {'status': 'SUCCESS'})
    world.update_observed('report', True, 'old file existed')
    goal = coordinator.create_goal('Create report', [file_step('report', 'storage/missing.txt')])
    assert coordinator.advance(goal['goal_id'])['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    assert world.observed('report') is None


def test_real_call_method_binds_reply_and_cleans_pending_context():
    import asyncio
    import re
    import secrets
    import time
    from types import MethodType
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'dashboard/server.py').read_text())
    names = {'call_device', 'accept_capability_reply'}
    methods = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    ns = dict(asyncio=asyncio, time=time, re=re, secrets=secrets, _interaction_event=lambda *args, **kw: None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])), '<device roundtrip>', 'exec'), ns)
    health = []
    host = SimpleNamespace(_device_pending_targets={}, _device_pending_calls={}, _device_sockets={},
        _mesh=SimpleNamespace(authorized=lambda *args: True, record_capability_result=lambda *args, **kw: health.append(args)))
    host.accept_capability_reply = MethodType(ns['accept_capability_reply'], host)
    class Socket:
        async def send_json(self, msg):
            assert host._device_pending_targets[msg['call_id']] == ('phone', self, 'app.inspect')
            reply = dict(type='capability.result', call_id=msg['call_id'], capability='app.inspect',
                         ok=True, status='SUCCESS', verified=True, evidence={'active_package': 'example'})
            assert not host.accept_capability_reply('other-phone', self, reply)
            assert host.accept_capability_reply('phone', self, reply)
    host._device_sockets['phone'] = Socket()
    result = asyncio.run(ns['call_device'](host, 'phone', 'app.inspect'))
    assert result['verified'] is True and len(health) == 1
    assert host._device_pending_targets == host._device_pending_calls == {}
