"""Validation hardening without claiming OS-level isolation."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from core import repair_engine as repair


def test_validator_child_does_not_inherit_secrets_or_python_hooks(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only-secret')
    monkeypatch.setenv('UNKNOWN_DEPLOYMENT_SECRET','test-only-secret')
    monkeypatch.setenv('PYTHONSTARTUP','/outside/startup.py')
    monkeypatch.setenv('PYTHONPATH','/outside/imports')
    env=repair._validator_environment(tmp_path,tmp_path/'home')
    proc=subprocess.run([sys.executable,'-c',
        "import os,json; print(json.dumps({k:os.environ.get(k) for k in ['OPENAI_API_KEY','UNKNOWN_DEPLOYMENT_SECRET','PYTHONSTARTUP','HOME','PYTHONPATH','PYTHONNOUSERSITE','PYTEST_DISABLE_PLUGIN_AUTOLOAD']}))"],
        env=env,capture_output=True,text=True,check=True)
    data=json.loads(proc.stdout)
    assert data['OPENAI_API_KEY'] is None and data['UNKNOWN_DEPLOYMENT_SECRET'] is None
    assert data['PYTHONSTARTUP'] is None
    assert data['HOME']==str(tmp_path/'home') and data['PYTHONPATH']==str(tmp_path)
    assert data['PYTHONNOUSERSITE']=='1' and data['PYTEST_DISABLE_PLUGIN_AUTOLOAD']=='1'


@pytest.mark.parametrize('path',['core/local_api_auth.py','core/LOCAL_API_AUTH.py',
                                 'core/server_export_policy.py','core/REPAIR_ENGINE.py'])
def test_authority_files_cannot_be_repaired_even_with_high_risk_approval(path):
    with pytest.raises(repair.RepairPolicyError,match='protected'):
        repair.enforce_policy([path],100,'high',True)


def test_symlink_alias_cannot_bypass_protected_file_name(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'BASE_DIR',tmp_path)
    (tmp_path/'core').mkdir()
    (tmp_path/'core/repair_engine.py').write_text('# immutable')
    (tmp_path/'core/ordinary.py').symlink_to(tmp_path/'core/repair_engine.py')
    with pytest.raises(repair.RepairPolicyError,match='symlink'):
        repair.enforce_policy(['core/ordinary.py'],100,'low',False)
    assert (tmp_path/'core/repair_engine.py').read_text()=='# immutable'


def test_symlink_directory_cannot_bypass_guard(tmp_path,monkeypatch):
    monkeypatch.setattr(repair,'BASE_DIR',tmp_path)
    (tmp_path/'core').mkdir()
    (tmp_path/'actions').mkdir()
    (tmp_path/'actions/alias').symlink_to(tmp_path/'core',target_is_directory=True)
    with pytest.raises(repair.RepairPolicyError,match='symlink'):
        repair.normalize_rel('actions/alias/repair_engine.py')


def test_validation_copy_never_follows_external_or_internal_symlinks(tmp_path,monkeypatch):
    repo=tmp_path/'repo'; (repo/'core').mkdir(parents=True)
    secret=tmp_path/'private.txt';secret.write_text('test-only-secret')
    (repo/'core/example.py').write_text('# source')
    (repo/'core/linked.py').symlink_to(secret)
    (repo/'core/alias.py').symlink_to(repo/'core/example.py')
    monkeypatch.setattr(repair,'BASE_DIR',repo)
    def validate(root,files,timeout):
        assert not (root/'core/linked.py').exists()
        assert not (root/'core/alias.py').exists()
        assert (root/'core/example.py').read_text()=='# candidate'
        return True,[]
    monkeypatch.setattr(repair,'_run_validators',validate)
    assert repair.validate_sandbox({'core/example.py':'# candidate'})==(True,[])
    assert secret.read_text()=='test-only-secret'
