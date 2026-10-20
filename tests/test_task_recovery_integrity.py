"""Interrupted side effects require reconciliation, never blind execution replay."""
import copy
import json
from types import SimpleNamespace

import pytest

from core import task_continuity as tc
from core.autonomy_engine import AutonomousCoordinator, state_verifier
from core.autonomy_state import GoalStore, WorldState
from core.capability_registry import Capability, CapabilityRegistry


def setup_goal(tmp_path, executor):
    store, world, caps = GoalStore(tmp_path), WorldState(tmp_path), CapabilityRegistry()
    caps.register(Capability('send', device_id='phone'))
    coordinator = AutonomousCoordinator(store, world, caps, executor, state_verifier)
    goal = coordinator.create_goal('Send once', [{'id': 'send-1', 'capability': 'send',
        'verify': {'section': 'delivery', 'equals': 'received'}}])
    return store, world, coordinator, goal['goal_id']


def test_restart_after_side_effect_does_not_execute_again(tmp_path):
    calls = []
    def interrupted(*args):
        calls.append('sent')
        raise ConnectionError('result lost')
    store, world, coordinator, gid = setup_goal(tmp_path, interrupted)
    with pytest.raises(ConnectionError):
        coordinator.advance(gid)
    restarted = AutonomousCoordinator(GoalStore(tmp_path), WorldState(tmp_path), coordinator.capabilities,
        lambda *args: calls.append('duplicate'), state_verifier)
    result = restarted.advance(gid)
    assert calls == ['sent']
    assert result['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    assert result['active_step']['id'] == 'send-1'
    restarted.world.update_observed('delivery', 'received', 'recipient readback')
    assert restarted.advance(gid)['status'] == 'GOAL_ACHIEVED'
    assert restarted.advance(gid)['status'] == 'GOAL_ACHIEVED'
    assert calls == ['sent']


def test_stale_or_unrelated_observation_cannot_confirm_interrupted_step(tmp_path):
    def interrupted(*args):
        raise ConnectionError('unknown')
    store, world, coordinator, gid = setup_goal(tmp_path, interrupted)
    world.update_observed('delivery', 'received', 'old delivery')
    with pytest.raises(ConnectionError):
        coordinator.advance(gid)
    world.update_observed('battery', 100, 'unrelated inspection')
    assert coordinator.advance(gid)['completed_steps'] == []
    assert store.load(gid)['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    world.update_observed('delivery', 'received', 'new readback')
    assert coordinator.advance(gid)['status'] == 'GOAL_ACHIEVED'


def test_verifier_crash_retains_result_without_reexecution(tmp_path):
    calls = []
    store, world, coordinator, gid = setup_goal(tmp_path,
        lambda *args: calls.append('sent') or {'status': 'SUCCESS', 'receipt': 'r1'})
    def broken(*args):
        raise RuntimeError('verification interrupted')
    coordinator.verifier = broken
    with pytest.raises(RuntimeError):
        coordinator.advance(gid)
    assert store.load(gid)['active_step']['result']['receipt'] == 'r1'
    coordinator.verifier = state_verifier
    world.update_observed('delivery', 'received', 'recipient receipt r1')
    assert coordinator.advance(gid)['status'] == 'GOAL_ACHIEVED'
    assert calls == ['sent']


def test_legacy_interrupted_goal_is_not_replayed_even_after_resume(tmp_path):
    calls = []
    store, world, coordinator, gid = setup_goal(tmp_path, lambda *args: calls.append(1))
    goal = store.load(gid)
    goal['status'] = 'EXECUTING'
    store.save(goal)
    store.reconcile(gid)
    assert coordinator.advance(gid)['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    assert calls == []


def isolate_task(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, 'STATE_DIR', tmp_path)
    monkeypatch.setattr(tc, 'STATE_FILE', tmp_path / 'active_task.json')


def test_late_result_cannot_overwrite_new_task_or_action(tmp_path, monkeypatch):
    isolate_task(tmp_path, monkeypatch)
    tc.begin('old', origin_device_id='phone')
    old = tc.action_started('send', {})
    tc.begin('new', origin_device_id='phone')
    current = tc.action_started('send', {})
    before = copy.deepcopy(tc.active())
    tc.action_finished('send', {'verified': True}, old)
    assert tc.active() == before
    tc.action_finished('send', {'verified': True}, current)
    finished = tc.active()['last_action']
    tc.action_finished('send', {'verified': False}, current)
    assert tc.active()['last_action'] == finished


def test_same_goal_from_another_device_is_not_reused(tmp_path, monkeypatch):
    isolate_task(tmp_path, monkeypatch)
    first = tc.begin('send', origin_device_id='phone')
    second = tc.begin('send', origin_device_id='desktop')
    assert first['task_id'] != second['task_id']
    assert second['origin_device_id'] == 'desktop'


def test_checkpoint_replay_does_not_duplicate_memory(tmp_path, monkeypatch):
    isolate_task(tmp_path, monkeypatch)
    tc.begin('send')
    aid = tc.action_started('send', {})
    tc.action_finished('send', {'verified': True}, aid)
    tc.checkpoint('sent', 'receipt')
    tc.checkpoint('sent again', 'same receipt')
    assert len(tc.active()['verified_checkpoints']) == 1


@pytest.mark.parametrize('content', ['{', '[]', '{"unexpected": true}'])
def test_corrupt_task_state_is_preserved(tmp_path, monkeypatch, content):
    isolate_task(tmp_path, monkeypatch)
    tc.STATE_FILE.write_text(content)
    with pytest.raises(ValueError):
        tc.begin('replacement')
    assert tc.STATE_FILE.read_text() == content


def test_running_approval_does_not_expire_replay_protection(monkeypatch):
    from core import confirm
    monkeypatch.setattr(confirm, '_pending', None)
    monkeypatch.setattr(confirm, '_recent_proposals', {'text_proposal:long': (0, 'running')})
    monkeypatch.setattr(confirm, 'time', SimpleNamespace(monotonic=lambda: 1000))
    monkeypatch.setattr(confirm, '_show_cb', lambda *args: pytest.fail('duplicate approval'))
    assert 'CONFIRMATION_COMPLETED' in confirm.request('text_proposal:long', 'Run', 'Same', lambda: None)
    assert confirm.pending_request() is None


@pytest.mark.parametrize('kind', ['goal', 'memory'])
def test_persistent_identifiers_reject_traversal_and_symlink(tmp_path, kind):
    from core.agent_memory import AgentMemory
    store = GoalStore(tmp_path) if kind == 'goal' else AgentMemory(tmp_path)
    load = store.load if kind == 'goal' else store.get
    with pytest.raises(ValueError):
        load('../outside')
    outside = tmp_path / 'outside.json'
    outside.write_text(json.dumps({'private': True}))
    (store.dir / ('a' * 32 + '.json')).symlink_to(outside)
    with pytest.raises(ValueError):
        load('a' * 32)
    assert json.loads(outside.read_text()) == {'private': True}


@pytest.mark.parametrize('change', ['session', 'user', 'action', 'none'])
def test_delayed_recovery_only_reaches_original_unchanged_session(change):
    import ast
    import asyncio
    from pathlib import Path
    calls = []
    class Session:
        async def send_client_content(self, **kwargs):
            calls.append(kwargs)
    session = Session()
    runtime = SimpleNamespace(session=session, _current_user_transcript='original')
    state = {'last_action': {'id': 'a', 'state': 'STARTED'}}
    async def delay(*args):
        if change == 'session':
            runtime.session = Session()
        elif change == 'user':
            runtime._current_user_transcript = 'new request'
        elif change == 'action':
            state['last_action'] = {'id': 'b', 'state': 'STARTED'}
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == '_resume_unfinished_task')
    namespace = dict(self=runtime, asyncio=SimpleNamespace(sleep=delay),
        task_state=SimpleNamespace(active=lambda: state, recovery_instruction=lambda: 'inspect first'),
        _recovery_session=session, _recovery_user='original', _recovery_action=copy.deepcopy(state['last_action']))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<delayed recovery>', 'exec'), namespace)
    asyncio.run(namespace['_resume_unfinished_task']())
    assert len(calls) == (1 if change == 'none' else 0)


def test_unverified_result_is_inspected_without_repeating_side_effect(tmp_path):
    calls = []
    store, world, coordinator, gid = setup_goal(tmp_path,
        lambda *args: calls.append('sent') or {'status': 'SUCCESS'})
    assert coordinator.advance(gid)['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    assert coordinator.advance(gid)['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    assert calls == ['sent']
    world.update_observed('delivery', 'received', 'readback')
    assert coordinator.advance(gid)['status'] == 'GOAL_ACHIEVED'
    assert calls == ['sent']


def test_explicit_failure_cannot_trigger_unsafe_automatic_retry(tmp_path):
    calls = []
    store, world, coordinator, gid = setup_goal(tmp_path,
        lambda *args: calls.append('attempt') or {'status': 'FAILED', 'reason': 'partial failure'})
    assert coordinator.advance(gid)['status'] == 'NO_SAFE_PROGRESS_POSSIBLE'
    coordinator.advance(gid)
    assert calls == ['attempt']


def test_concurrent_advances_execute_step_once_in_one_process(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    calls = []
    def execute(*args):
        calls.append('sent')
        world.update_observed('delivery', 'received', 'receipt')
        return {'status': 'SUCCESS'}
    store, world, coordinator, gid = setup_goal(tmp_path, execute)
    other = AutonomousCoordinator(GoalStore(tmp_path), world, coordinator.capabilities, execute, state_verifier)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: (coordinator if n % 2 else other).advance(gid), range(8)))
    assert calls == ['sent']
    assert all(result['status'] == 'GOAL_ACHIEVED' for result in results)


def test_model_observe_cannot_forge_independent_world_evidence(tmp_path, monkeypatch):
    from actions import autonomous_goal
    world = WorldState(tmp_path)
    monkeypatch.setattr(autonomous_goal, '_WORLD', world)
    result = json.loads(autonomous_goal.autonomous_goal({'operation': 'observe', 'section': 'delivery', 'value': 'received'}))
    assert result['status'] == 'UNVERIFIED' and result['verified'] is False
    assert world.observed('delivery') is None
    assert world.data['expected']['delivery']['claim'] == 'received'


def test_legacy_model_observation_is_not_verification_evidence(tmp_path):
    world = WorldState(tmp_path)
    world.data['observed']['delivery'] = {'value': 'received', 'evidence': 'autonomous_goal observation'}
    result = state_verifier({'capability': 'send', 'verify': {'section': 'delivery', 'equals': 'received'}},
        {'status': 'SUCCESS'}, world, {})
    assert result['verified'] is False
    assert result['reason'] == 'host_observation_required'
