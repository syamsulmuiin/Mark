"""Fixed-repository script updates and detached, observable server restarts."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

BASE_DIR = Path(__file__).resolve().parents[1]
_LOCK = threading.RLock()
_ALLOWED_REMOTES = {'https://github.com/syamsulmuiin/Mark', 'https://github.com/syamsulmuiin/Mark.git',
                    'git@github.com:syamsulmuiin/Mark.git', 'ssh://git@github.com/syamsulmuiin/Mark.git'}
_ACTIVE = {'scheduled', 'restarting'}


def _state_path():
    return BASE_DIR / 'runtime' / 'maintenance.json'


def _read_state():
    try:
        return json.loads(_state_path().read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise RuntimeError('Maintenance state is unreadable; inspect runtime/maintenance.json') from None


def _save_state(state):
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state), encoding='utf-8')
    os.replace(temp, path)
    from core.interaction_log import write_event
    write_event(path.parent / 'interaction.log', 'server_maintenance', status=state['status'])


def _git(*args, allow_failure=False):
    result = subprocess.run(['git', *args], cwd=BASE_DIR, capture_output=True, timeout=60,
                            env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode and not allow_failure:
        # Git errors may contain credentials embedded in remote URLs; never echo them.
        raise RuntimeError('Git operation failed; inspect repository access, connectivity and local state')
    return result


def _text(*args):
    return _git(*args).stdout.decode('utf-8').strip()


def _checkout():
    if Path(_text('rev-parse', '--show-toplevel')).resolve() != BASE_DIR.resolve():
        raise RuntimeError('Mark must run from its own Git checkout')
    if _text('config', '--get', 'remote.origin.url') not in _ALLOWED_REMOTES:
        raise RuntimeError('Update requires the official syamsulmuiin/Mark GitHub origin')
    if _text('branch', '--show-current') != 'main':
        raise RuntimeError('Update requires the main branch; no branch switch is performed')
    if _text('status', '--porcelain'):
        raise RuntimeError('Local changes or untracked files exist; update stopped without overwriting them')


def _candidate():
    _checkout()
    _git('fetch', '--no-tags', 'origin', 'main')
    current, target = _text('rev-parse', 'HEAD'), _text('rev-parse', 'FETCH_HEAD')
    if _git('merge-base', '--is-ancestor', current, target, allow_failure=True).returncode:
        raise RuntimeError('Local history diverged or is ahead; automatic update is not allowed')
    changed = _text('diff', '--name-only', current, target).splitlines()
    dependencies = any(Path(name).name.startswith('requirements') or Path(name).name in
                       {'pyproject.toml', 'poetry.lock', 'uv.lock', 'setup.py', 'setup.cfg'} for name in changed)
    return current, target, changed, dependencies


def _validate(target):
    paths = _text('ls-tree', '-r', '--name-only', target).splitlines()
    for path in paths:
        if path.endswith('.py') and (path.startswith(('core/', 'actions/', 'dashboard/')) or path in {'main.py', 'setup.py'}):
            data = _git('show', f'{target}:{path}').stdout
            try:
                compile(data, path, 'exec')
            except (SyntaxError, ValueError):
                raise RuntimeError(f'Update rejected: Python syntax validation failed in {path}') from None


def _schedule_restart():
    state = {'status': 'scheduled', 'scheduled_at': time.time(), 'verified': False,
             'message': 'Restart scheduled in 10 seconds; connection will briefly disconnect. Check status after reconnect.'}
    _save_state(state)
    log = BASE_DIR / 'runtime' / 'maintenance.log'
    try:
        with log.open('ab') as output:
            options = {'start_new_session': True} if os.name != 'nt' else {
                'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
            process = subprocess.Popen([sys.executable, '-m', 'core.server_maintenance', '--restart-helper'],
                cwd=BASE_DIR, stdin=subprocess.DEVNULL, stdout=output, stderr=output, **options)
        state['helper_pid'] = process.pid
        _save_state(state)
    except Exception:
        _save_state({'status': 'failed', 'verified': False, 'message': 'Restart helper could not start'})
        raise
    return {'ok': True, 'status': 'WAITING', 'verified': False, 'executed': False, **{'restart': state}}


def maintain(operation='status'):
    with _LOCK:
        if operation == 'status':
            state = _read_state()
            outcome = 'WAITING' if state.get('status') in _ACTIVE | {'dependencies_required'} else 'FAILED' if state.get('status') == 'failed' else 'VERIFIED'
            return {'ok': outcome != 'FAILED', 'status': outcome, 'verified': outcome == 'VERIFIED', 'maintenance': state,
                    'operations': ['check', 'update', 'restart', 'update_restart'],
                    'instruction': 'A scheduled restart is not completed; report its recorded state accurately.'}
        if operation not in {'check', 'update', 'restart', 'update_restart'}:
            raise ValueError('Unknown server maintenance operation')
        previous = _read_state()
        if previous.get('status') in _ACTIVE:
            return {'ok': True, 'status': 'WAITING', 'verified': False, 'maintenance': previous,
                    'message': 'A restart is already pending; do not schedule it again. If stuck, inspect runtime/maintenance.log.'}
        if operation == 'restart':
            return _schedule_restart()
        current, target, changed, dependencies = _candidate()
        result = {'ok': True, 'status': 'VERIFIED', 'verified': True, 'current_commit': current,
                  'target_commit': target, 'update_available': current != target,
                  'dependencies_changed': dependencies, 'changed_files': len(changed)}
        if operation == 'check':
            return result
        _validate(target)
        _checkout()  # Recheck after fetch/validation before changing local files.
        if _text('rev-parse', 'HEAD') != current:
            raise RuntimeError('Checkout changed during validation; check again before updating')
        _git('merge', '--ff-only', target)
        if _text('rev-parse', 'HEAD') != target:
            raise RuntimeError('Updated commit did not verify')
        result.update(updated=current != target, current_commit=target, restart_required=current != target)
        dependencies = dependencies or previous.get('dependencies_required') is True
        _save_state({'status': 'dependencies_required' if dependencies else 'updated',
                     'verified': not dependencies, 'checkout_commit': target,
                     'dependencies_required': dependencies, 'restart_required': current != target,
                     'message': 'Checkout state only; running process is not activated by a Git update.'})
        if dependencies:
            result.update(status='WAITING', verified=False, activation_required='install_dependencies_then_restart',
                          message='Scripts updated. Dependency files changed; install dependencies before restarting. No packages were installed.')
            return result
        if operation == 'update_restart':
            result.update(_schedule_restart())
        else:
            result['message'] = 'Script update verified; running process needs restart to activate changes.'
        return result


def _restart_helper():
    # Detached process survives termination of the worker that requested restart.
    time.sleep(10)
    try:
        _save_state({'status': 'restarting', 'verified': False, 'started_at': time.time()})
        from core.server_lifecycle import _restart_server, _local_server_identity
        pid = _restart_server()
        if not pid or _local_server_identity(timeout=3) != pid:
            raise RuntimeError('Replacement worker did not become ready')
        _save_state({'status': 'completed', 'verified': True, 'worker_pid': pid, 'finished_at': time.time()})
    except Exception as exc:
        _save_state({'status': 'failed', 'verified': False, 'error_type': type(exc).__name__,
                     'message': 'Restart failed; inspect runtime/error.log and runtime/maintenance.log'})


if __name__ == '__main__' and sys.argv[1:] == ['--restart-helper']:
    _restart_helper()
