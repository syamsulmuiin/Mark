import json
import subprocess
from pathlib import Path

import pytest
from core import repair_engine as repair


def test_copy_failure_returns_bounded_diagnostic_without_sensitive_exception(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'BASE_DIR',tmp_path)
    monkeypatch.setattr(repair.shutil,'copytree',lambda *a,**kw: (_ for _ in ()).throw(OSError('private-token-value')))
    ok,results=repair.validate_sandbox({'core/example.py':'x = 2'})
    assert not ok and results[0]['stage']=='copy_source'
    assert 'private-token-value' not in json.dumps(results)


def test_process_launch_failure_is_validation_failure_not_uncaught_exception(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'select_related_tests',lambda *a:[])
    monkeypatch.setattr(repair,'audit',lambda *a,**kw:None)
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw: (_ for _ in ()).throw(PermissionError('private-path')))
    ok,results=repair._run_validators(tmp_path,[],1)
    assert not ok and len(results)==1
    assert results[0]['stage']=='validator_launch' and results[0]['error_type']=='PermissionError'
    assert 'private-path' not in json.dumps(results)


def prepare(tmp_path,monkeypatch):
    from test_self_repair import _sandbox,_apply_params
    from actions import self_repair_apply as action
    _sandbox(monkeypatch,tmp_path)
    monkeypatch.setattr(action,'BASE_DIR',tmp_path)
    (tmp_path/'core').mkdir(exist_ok=True)
    (tmp_path/'core/example.py').write_text('x = 1\n')
    return action,_apply_params()


def test_actual_copy_failure_closes_transaction_and_preserves_source(tmp_path,monkeypatch):
    action,params=prepare(tmp_path,monkeypatch)
    monkeypatch.setattr(repair.shutil,'copytree',lambda *a,**kw: (_ for _ in ()).throw(OSError('disk full')))
    result=json.loads(action.self_repair_apply(params))
    assert result['status']=='FAILED' and result['source_modified'] is False
    assert (tmp_path/'core/example.py').read_text()=='x = 1\n'
    manifest=json.loads((repair.TX_DIR/result['transaction_id']/'manifest.json').read_text())
    assert manifest['status']=='REJECTED_SANDBOX'
    assert result['validation'][0]['stage']=='copy_source'


@pytest.mark.parametrize('stage',['prepare_snapshot','persist_validation_failure'])
def test_snapshot_or_status_io_failure_returns_explicit_unchanged_result(tmp_path,monkeypatch,stage):
    action,params=prepare(tmp_path,monkeypatch)
    if stage=='prepare_snapshot':
        monkeypatch.setattr(action,'begin_transaction',lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    else:
        monkeypatch.setattr(action,'validate_sandbox',lambda *a:(False,[{'returncode':-1}]))
        monkeypatch.setattr(action,'set_status',lambda *a,**kw: (_ for _ in ()).throw(OSError('disk full')))
    result=json.loads(action.self_repair_apply(params))
    assert result['status']=='FAILED' and result['source_modified'] is False
    assert result['failure_stage']==stage
    assert (tmp_path/'core/example.py').read_text()=='x = 1\n'
