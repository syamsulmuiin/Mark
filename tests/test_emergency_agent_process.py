"""Real-process emergency termination preserves the service and goal evidence."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

from core.autonomy_engine import AgentProcessManager, emergency_break
from core.autonomy_state import AgentRuntimeState, GoalStore

ROOT=Path(__file__).resolve().parents[1]

def skip_pid_namespace():
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        pytest.fail('CI must expose real subprocess PIDs for emergency-stop validation')
    pytest.skip('Hosted /proc does not expose the subprocess PID namespace')


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(ROOT), str(ROOT/'tests'), os.environ.get('PYTHONPATH','')]))
    value=AgentProcessManager(tmp_path)
    yield value
    value.stop()


def wait_for(path, future=None):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        if path.exists():
            try:return json.loads(path.read_text())
            except ValueError:pass
        if future is not None and future.done():
            result=future.result()
            if result.get('reason')=='worker_identity_unavailable':
                skip_pid_namespace()
            pytest.fail(str(result))
        time.sleep(.01)
    pytest.fail('worker did not start')


def test_child_execution_and_rpc_do_not_run_in_service_process(manager):
    result=manager.run('emergency_worker_tasks:echo',{'value':42})
    if result.get('reason')=='worker_identity_unavailable':skip_pid_namespace()
    assert result['pid'] != os.getpid() and result['echo']=={'value':42}
    assert manager.state.read()['status']=='idle'
    assert 'Worker output' in (manager.state.path.parent/'agent_worker.log').read_text()


def test_worker_device_bridge_roundtrip(manager):
    result=manager.run('emergency_worker_tasks:roundtrip',{},device_rpc=lambda *a:{'ok':True})
    if result.get('reason')=='worker_identity_unavailable':skip_pid_namespace()
    assert result=={'ok':True}


def test_external_main_break_kills_cpu_loop_and_resets_idle(manager, tmp_path):
    store=GoalStore(tmp_path/'storage/autonomy')
    goal=store.create('Keep evidence')
    goal.update(status='EXECUTING',active_step={'id':'running','result':'unknown'})
    store.save(goal)
    marker=tmp_path/'started.json'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(manager.run,'emergency_worker_tasks:spin',{'marker':str(marker)},goal_id=goal['goal_id'])
        process=wait_for(marker, future)
        assert process['pid'] != os.getpid()
        script=("import sys,runpy;from pathlib import Path;from core import autonomy_state;"
                "autonomy_state.ROOT=Path(sys.argv[1]);sys.argv=['main.py','--break'];"
                f"runpy.run_path({str(ROOT/'main.py')!r},run_name='__main__')")
        result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],capture_output=True,text=True,timeout=8)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['status']=='idle'
        assert future.result(timeout=5)['status']=='CANCELLED'
    assert manager.pid is None and manager.state.read()['reason']=='emergency_stop'
    preserved=store.load(goal['goal_id'])
    assert preserved['status']=='INTERRUPTED' and preserved['active_step']['id']=='running'
    assert not psutil.pid_exists(process['pid'])
    assert psutil.Process(os.getpid()).is_running()


def test_stop_kills_worker_descendants_and_service_survives(manager, tmp_path):
    marker=tmp_path/'descendants.json'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(manager.run,'emergency_worker_tasks:spin',{'marker':str(marker),'descendant':True})
        info=wait_for(marker, future)
        assert manager.stop()['status']=='idle'
        future.result(timeout=5)
    try:
        child=psutil.Process(info['child'])
        assert child.status()==psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:pass
    assert psutil.Process(os.getpid()).is_running()


def test_unrelated_pid_is_not_killed_and_mismatch_is_not_reported_idle(manager):
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])
    try:
        try:created=psutil.Process(process.pid).create_time()
        except psutil.NoSuchProcess:skip_pid_namespace()
        with manager.state.locked():
            manager.state.write({'status':'running','pid':process.pid,'owner_pid':os.getpid(),
                'create_time':created,'run_id':'not-the-worker'})
        result=manager.stop()
        assert result['status']=='FAILED' and result['reason']=='worker_identity_mismatch'
        assert process.poll() is None
    finally:
        process.kill();process.wait()
        with manager.state.locked():manager.state.write({'status':'idle','pid':None})


def test_stale_cleanup_cannot_clear_a_newer_worker_record(manager):
    with manager.state.locked():manager.state.write({'status':'running','run_id':'new','pid':123})
    manager.state.finish('old')
    assert manager.state.read()['run_id']=='new' and manager.pid==123
    with manager.state.locked():manager.state.write({'status':'idle','pid':None})


def test_break_cli_option_is_distinct_from_stopping_server():
    from core.server_lifecycle import _runtime_mode
    assert _runtime_mode(['--break'])=='break'
    assert _runtime_mode(['--stop'])=='stop'


def test_global_hook_dispatches_stop_outside_keyboard_callback(monkeypatch):
    import threading
    from types import SimpleNamespace
    from core.hotkey import EmergencyHotkey
    callbacks={}
    class Listener:
        def __init__(self, mapping):callbacks.update(mapping);self.alive=False
        def start(self):self.alive=True
        def wait(self):pass
        def is_alive(self):return self.alive
        def stop(self):self.alive=False
        def join(self, timeout=None):pass
    monkeypatch.setitem(sys.modules,'pynput',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'pynput.keyboard',SimpleNamespace(GlobalHotKeys=Listener))
    done=threading.Event()
    threads=[]
    monitor=EmergencyHotkey(lambda:(threads.append(threading.get_ident()),done.set()))
    assert monitor.start() and monitor.active
    callbacks[monitor.chord]()
    assert done.wait(2) and threads[0]!=threading.get_ident()
    monitor.stop()
    assert not monitor.active


def test_keyboard_permission_failure_is_reported_without_window_fallback(monkeypatch):
    from types import SimpleNamespace
    from core.hotkey import EmergencyHotkey
    def denied(*args):raise PermissionError('No user input session')
    monkeypatch.setitem(sys.modules,'pynput',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'pynput.keyboard',SimpleNamespace(GlobalHotKeys=denied))
    hook=EmergencyHotkey(lambda:None)
    assert not hook.start() and hook.last_error=='PermissionError' and not hook.active


def test_emergency_authority_files_are_immutable_to_self_repair():
    from core.repair_engine import is_protected
    for path in ('core/hotkey.py','core/agent_worker.py','core/autonomy_engine.py',
                 'core/autonomy_state.py','core/server_lifecycle.py','actions/autonomous_goal.py','main.py'):
        assert is_protected(path)


def test_interrupted_goal_cannot_resume_its_active_step_automatically(tmp_path):
    from core.autonomy_engine import AutonomousCoordinator, state_verifier
    from core.autonomy_state import WorldState
    from core.capability_registry import CapabilityRegistry
    store=GoalStore(tmp_path)
    goal=store.create('Interrupted action')
    goal.update(status='INTERRUPTED', active_step={'id':'old'}, plan=[])
    store.save(goal)
    called=[]
    coordinator=AutonomousCoordinator(store,WorldState(tmp_path),CapabilityRegistry(),
        lambda *a:called.append(1),state_verifier,observer=lambda *a:called.append(2))
    assert coordinator.advance(goal['goal_id'])['status']=='INTERRUPTED' and called==[]


def test_restart_refuses_to_orphan_an_unconfirmed_agent_worker(monkeypatch):
    from core import server_lifecycle, autonomy_engine
    monkeypatch.setattr(autonomy_engine,'emergency_break',lambda *a:{'status':'FAILED'})
    monkeypatch.setattr(server_lifecycle,'_server_pid',lambda:None)
    monkeypatch.setattr(server_lifecycle,'_spawn_server',lambda:pytest.fail('replacement must not launch'))
    assert server_lifecycle._restart_server() is None
