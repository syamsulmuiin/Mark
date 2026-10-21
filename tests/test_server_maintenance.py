import json
from pathlib import Path
import subprocess

import pytest
from core import server_maintenance as maintenance
from core.action_policy import requires_confirmation


def git(path,*args):
    return subprocess.run(['git',*args],cwd=path,check=True,capture_output=True,text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path,monkeypatch):
    upstream=tmp_path/'upstream'; upstream.mkdir()
    git(upstream,'init','-b','main'); git(upstream,'config','user.email','test@example.test'); git(upstream,'config','user.name','Test')
    (upstream/'.gitignore').write_text('runtime/\n')
    (upstream/'main.py').write_text('value=1\n')
    git(upstream,'add','.'); git(upstream,'commit','-m','initial')
    working=tmp_path/'working'
    git(tmp_path,'clone',str(upstream),str(working))
    git(working,'config','user.email','test@example.test'); git(working,'config','user.name','Test')
    monkeypatch.setattr(maintenance,'BASE_DIR',working)
    monkeypatch.setattr(maintenance,'_ALLOWED_REMOTES',{str(upstream)})
    return upstream,working


def commit(upstream,name,text):
    target=upstream/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text)
    git(upstream,'add','.'); git(upstream,'commit','-m','update')
    return git(upstream,'rev-parse','HEAD')


def test_check_then_fast_forward_update_uses_exact_remote_commit(checkout):
    upstream,working=checkout
    target=commit(upstream,'main.py','value=2\n')
    before=git(working,'rev-parse','HEAD')
    check=maintenance.maintain('check')
    assert check['target_commit']==target and check['update_available']
    assert git(working,'rev-parse','HEAD')==before
    result=maintenance.maintain('update')
    assert result['verified'] and result['restart_required']
    assert git(working,'rev-parse','HEAD')==target
    assert (working/'main.py').read_text()=='value=2\n'


def test_dirty_checkout_is_not_overwritten(checkout):
    upstream,working=checkout
    commit(upstream,'main.py','value=2\n')
    (working/'main.py').write_text('local=True\n')
    with pytest.raises(RuntimeError,match='Local changes'):maintenance.maintain('update')
    assert (working/'main.py').read_text()=='local=True\n'


def test_diverged_checkout_is_not_reset(checkout):
    upstream,working=checkout
    commit(upstream,'main.py','remote=True\n'); commit(working,'local.py','local=True\n')
    before=git(working,'rev-parse','HEAD')
    with pytest.raises(RuntimeError,match='diverged'):maintenance.maintain('update')
    assert git(working,'rev-parse','HEAD')==before


def test_invalid_python_is_rejected_before_merge(checkout):
    upstream,working=checkout
    commit(upstream,'core/broken.py','def broken(:\n')
    before=git(working,'rev-parse','HEAD')
    with pytest.raises(RuntimeError,match='syntax'):maintenance.maintain('update')
    assert git(working,'rev-parse','HEAD')==before


def test_dependency_update_does_not_restart(checkout,monkeypatch):
    upstream,working=checkout
    commit(upstream,'requirements.txt','new-package==1.0\n')
    monkeypatch.setattr(maintenance,'_schedule_restart',lambda:pytest.fail('do not restart before dependency installation'))
    result=maintenance.maintain('update_restart')
    assert result['status']=='WAITING' and result['activation_required']=='install_dependencies_then_restart'
    assert (working/'requirements.txt').exists()
    assert maintenance.maintain('update_restart')['status']=='WAITING'
    assert maintenance.maintain('status')['maintenance']['dependencies_required'] is True


def test_unexpected_origin_is_rejected_without_network(checkout):
    upstream,working=checkout
    git(working,'remote','set-url','origin','https://example.test/other')
    with pytest.raises(RuntimeError,match='official'):maintenance.maintain('update')


def test_pending_restart_is_not_scheduled_twice(tmp_path,monkeypatch):
    monkeypatch.setattr(maintenance,'BASE_DIR',tmp_path)
    maintenance._save_state({'status':'scheduled','verified':False})
    monkeypatch.setattr(maintenance,'_schedule_restart',lambda:pytest.fail('duplicate restart'))
    assert maintenance.maintain('restart')['status']=='WAITING'
    assert maintenance.maintain('status')['status']=='WAITING'


@pytest.mark.parametrize('healthy',[True,False])
def test_detached_helper_records_actual_health_result(tmp_path,monkeypatch,healthy):
    from core import server_lifecycle
    monkeypatch.setattr(maintenance,'BASE_DIR',tmp_path)
    monkeypatch.setattr(maintenance.time,'sleep',lambda _:None)
    monkeypatch.setattr(server_lifecycle,'_restart_server',lambda:12345)
    monkeypatch.setattr(server_lifecycle,'_local_server_identity',lambda **kw:12345 if healthy else None)
    maintenance._restart_helper()
    state=json.loads((tmp_path/'runtime/maintenance.json').read_text())
    assert state['status']==('completed' if healthy else 'failed')
    assert state['verified'] is healthy


@pytest.mark.parametrize('operation,approval',[('status',False),('check',False),('update',True),('restart',True),('update_restart',True)])
def test_mutating_maintenance_requires_single_host_gate(operation,approval):
    assert requires_confirmation('server_maintenance',{'operation':operation}) is approval


def test_inert_append_section_does_not_require_extra_approval():
    assert not requires_confirmation('document_editor',{'action':'append_section'})


def test_restart_launches_fixed_detached_helper_and_stays_waiting(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(maintenance,'BASE_DIR',tmp_path)
    calls=[]
    monkeypatch.setattr(maintenance.subprocess,'Popen',lambda command,**kwargs:calls.append((command,kwargs)) or SimpleNamespace(pid=12345))
    result=maintenance.maintain('restart')
    assert result['status']=='WAITING' and result['verified'] is False
    assert calls[0][0]==[maintenance.sys.executable,'-m','core.server_maintenance','--restart-helper']
    assert calls[0][1]['cwd']==tmp_path
    assert maintenance.maintain('status')['status']=='WAITING'


@pytest.mark.parametrize('state,status,phrase', [
    ({'status':'completed','verified':True}, 'VERIFIED', 'Restart completed'),
    ({'status':'scheduled'}, 'WAITING', 'not completed'),
    ({'status':'restarting'}, 'WAITING', 'not completed'),
    ({'status':'dependencies_required'}, 'WAITING', 'installation is required'),
    ({'status':'failed'}, 'FAILED', 'Maintenance failed'),
    ({'status':'updated'}, 'VERIFIED', 'Do not infer'),
    ({}, 'VERIFIED', 'Do not infer'),
])
def test_status_instruction_matches_recorded_operation(monkeypatch, state, status, phrase):
    monkeypatch.setattr(maintenance, '_read_state', lambda: state)
    result = maintenance.maintain('status')
    assert result['status'] == status
    assert phrase in result['instruction']
    assert result['maintenance'] == state


@pytest.mark.parametrize('restart',[False,True])
def test_dependency_helper_fixed_command_success(checkout,monkeypatch,restart):
    _, working = checkout
    (working/'requirements.txt').write_text('pytest\n')
    git(working,'add','.'); git(working,'commit','-m','requirements')
    maintenance._save_state({'status':'dependencies_scheduled','checkout_commit':git(working,'rev-parse','HEAD'),
                             'restart_after_install':restart,'dependencies_required':True})
    original = maintenance.subprocess.run
    calls, restarts = [], []
    def run(command, **kwargs):
        if command[0] == 'git': return original(command, **kwargs)
        calls.append((command,kwargs))
        return subprocess.CompletedProcess(command,0)
    monkeypatch.setattr(maintenance.subprocess,'run',run)
    monkeypatch.setattr(maintenance,'_schedule_restart',lambda:restarts.append(True))
    maintenance._dependencies_helper()
    state=maintenance._read_state()
    assert state['status']=='dependencies_installed' and not state['dependencies_required']
    assert calls[0][0]==[maintenance.sys.executable,'-m','pip','--isolated','install',
        '--disable-pip-version-check','--no-input','-r',str(working/'requirements.txt')]
    assert calls[1][0][-1]=='check'
    assert calls[0][1]['timeout']==600
    assert not any('KEY' in key or key.startswith('PIP_') for key in calls[0][1]['env'])
    assert bool(restarts) is restart


@pytest.mark.parametrize('failure',['install','check','timeout'])
def test_dependency_failure_never_restarts(checkout,monkeypatch,failure):
    _,working=checkout
    maintenance._save_state({'status':'dependencies_scheduled','checkout_commit':git(working,'rev-parse','HEAD'),
                             'restart_after_install':True})
    original=maintenance.subprocess.run
    def run(command,**kwargs):
        if command[0]=='git':return original(command,**kwargs)
        if failure=='timeout':raise subprocess.TimeoutExpired(command,600)
        return subprocess.CompletedProcess(command,1 if failure in command else 0)
    monkeypatch.setattr(maintenance.subprocess,'run',run)
    monkeypatch.setattr(maintenance,'_schedule_restart',lambda:pytest.fail('restart on failure'))
    maintenance._dependencies_helper()
    assert maintenance._read_state()['status']=='failed'
    assert maintenance._read_state()['dependencies_required']


def test_dependency_scheduling_and_gate(checkout,monkeypatch):
    _,working=checkout
    (working/'requirements.txt').write_text('pytest\n')
    git(working,'add','.');git(working,'commit','-m','requirements')
    calls=[]
    original = maintenance.subprocess.Popen
    monkeypatch.setattr(maintenance.subprocess,'Popen',lambda command,**kw: original(command,**kw) if command[0]=='git' else calls.append(command))
    result=maintenance.maintain('install_dependencies_restart')
    assert result['status']=='WAITING'
    assert calls==[[maintenance.sys.executable,'-m','core.server_maintenance','--dependencies-helper']]
    assert maintenance.maintain('install_dependencies_restart')['status']=='WAITING'
    assert len(calls)==1
    assert requires_confirmation('server_maintenance',{'operation':'install_dependencies_restart'})
