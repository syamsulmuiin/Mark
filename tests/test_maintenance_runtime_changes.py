import json
from pathlib import Path

import pytest
from core import server_maintenance as maintenance
import test_server_maintenance as fixtures

checkout = fixtures.checkout
git = fixtures.git
commit = fixtures.commit


ROOT = Path(__file__).resolve().parents[1]


def test_actual_gitignore_keeps_worker_state_clean_and_nested_source_visible(checkout):
    upstream,working=checkout
    commit(upstream,'.gitignore',(ROOT/'.gitignore').read_text())
    git(working,'pull','--ff-only')
    runtime=working/'runtime'; runtime.mkdir()
    for name in ['server.pid','maintenance.json','maintenance.tmp','error.log','interaction.log']:
        (runtime/name).write_text('generated')
    config=working/'config'; config.mkdir()
    (config/'api_keys.json').write_text('{}')
    (config/'certs').mkdir(); (config/'certs/server.crt').write_text('test certificate')
    (config/'token_google.json').write_text('{}')
    assert maintenance._local_changes()==[]
    nested=working/'desktop-companion/runtime/new_source.py'
    nested.parent.mkdir(parents=True); nested.write_text('value=1')
    assert maintenance._local_changes()==[{'status':'??','path':'desktop-companion/runtime/new_source.py'}]


def test_check_reports_remote_update_even_with_local_modifications(checkout):
    upstream,working=checkout
    target=commit(upstream,'main.py','remote_value=2\n')
    (working/'main.py').write_text('local_value=3\n')
    result=maintenance.maintain('check')
    assert result['update_available'] and result['target_commit']==target
    assert result['can_apply_update'] is False
    assert result['blocking_changes']==[{'status':' M','path':'main.py'}]
    assert (working/'main.py').read_text()=='local_value=3\n'
    with pytest.raises(maintenance.LocalChangesError):maintenance.maintain('update')


def test_check_does_not_mistake_local_changes_for_no_upstream_update(checkout):
    upstream,working=checkout
    (working/'local notes.txt').write_text('local data')
    result=maintenance.maintain('check')
    assert not result['update_available'] and not result['can_apply_update']
    assert result['blocking_changes']==[{'status':'??','path':'local notes.txt'}]


def test_blocked_action_returns_paths_and_logs_reason_without_contents(checkout):
    from actions.server_maintenance import server_maintenance
    upstream,working=checkout
    (working/'local notes.txt').write_text('private contents not for logs')
    result=json.loads(server_maintenance({'operation':'update'}))
    assert result['status']=='FAILED'
    assert result['blocking_changes']==[{'status':'??','path':'local notes.txt'}]
    log=(working/'runtime/interaction.log').read_text()
    assert 'server_maintenance_blocked' in log and 'local notes.txt' in log
    assert 'private contents' not in log


def test_rename_with_spaces_has_one_blocker_record(checkout):
    upstream,working=checkout
    git(working,'mv','main.py','renamed main.py')
    assert maintenance._local_changes()==[{'status':'R ','path':'renamed main.py'}]
