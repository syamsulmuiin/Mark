import json
from pathlib import Path

import pytest
from core import repair_engine as repair


def transaction(tmp_path,monkeypatch):
    from test_self_repair import _sandbox
    _sandbox(monkeypatch,tmp_path)
    for name,text in [('a.py','original A'),('b.py','original B')]:
        (tmp_path/name).write_text(text)
    txid=repair.begin_transaction('repair','low',{'a.py':'original A','b.py':'original B'},[])
    repair.write_candidate('a.py','candidate A'); repair.write_candidate('b.py','candidate B')
    repair.set_status(txid,'CANDIDATE_WRITTEN')
    return txid,repair.TX_DIR/txid


def test_corrupt_later_snapshot_prevents_all_restores(tmp_path,monkeypatch):
    txid,root=transaction(tmp_path,monkeypatch)
    (root/'snapshot/b.py').write_text('damaged')
    with pytest.raises(repair.RepairPolicyError,match='integrity'):
        repair.rollback(txid)
    assert (tmp_path/'a.py').read_text()=='candidate A'
    assert (tmp_path/'b.py').read_text()=='candidate B'


@pytest.mark.parametrize('target',['core/repair_engine.py','devices/identity.json',
                                  'config/provider_auth/openai_codex.json','requirements.txt'])
def test_modified_manifest_cannot_restore_authority_or_credentials(tmp_path,monkeypatch,target):
    txid,root=transaction(tmp_path,monkeypatch)
    path=tmp_path/target; path.parent.mkdir(parents=True,exist_ok=True);path.write_text('protected')
    snapshot=root/'snapshot'/target;snapshot.parent.mkdir(parents=True,exist_ok=True);snapshot.write_text('malicious')
    manifest=json.loads((root/'manifest.json').read_text())
    manifest['files']=[{'path':target,'sha256':repair.sha256_text('malicious')}]
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(repair.RepairPolicyError,match='protected'):
        repair.rollback(txid)
    assert path.read_text()=='protected'


def test_snapshot_symlink_is_rejected_even_with_matching_hash(tmp_path,monkeypatch):
    txid,root=transaction(tmp_path,monkeypatch)
    snapshot=root/'snapshot/a.py'; snapshot.unlink()
    external=tmp_path/'external';external.write_text('original A');snapshot.symlink_to(external)
    with pytest.raises(repair.RepairPolicyError,match='symlink'):
        repair.rollback(txid)
    assert (tmp_path/'a.py').read_text()=='candidate A'


def test_manifest_identifier_mismatch_blocks_recovery_and_new_repair(tmp_path,monkeypatch):
    txid,root=transaction(tmp_path,monkeypatch)
    manifest=json.loads((root/'manifest.json').read_text());manifest['id']='../other-transaction'
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(repair.RepairPolicyError,match='recovery failed'):
        repair.recover_incomplete_transactions()
    from actions import self_repair_apply as action
    from test_self_repair import _apply_params
    monkeypatch.setattr(action,'BASE_DIR',tmp_path)
    (tmp_path/'main.py').write_text('x = 1\n')
    result=json.loads(action.self_repair_apply(_apply_params()))
    assert result['status']=='FAILED' and result['failure_stage']=='recover_previous_transaction'
    assert (tmp_path/'main.py').read_text()=='x = 1\n'
    assert (tmp_path/'a.py').read_text()=='candidate A'


@pytest.mark.parametrize('txid',['../outside','/tmp/outside','not-a-transaction'])
def test_transaction_paths_cannot_escape_state_directory(txid):
    with pytest.raises(repair.RepairPolicyError,match='identifier'):
        repair.rollback(txid)


def test_valid_recovery_still_restores_all_originals(tmp_path,monkeypatch):
    txid,_=transaction(tmp_path,monkeypatch)
    assert repair.recover_incomplete_transactions()==[txid]
    assert (tmp_path/'a.py').read_text()=='original A'
    assert (tmp_path/'b.py').read_text()=='original B'


def test_candidate_and_rollback_preserve_existing_file_permissions(tmp_path,monkeypatch):
    import stat
    from test_self_repair import _sandbox
    _sandbox(monkeypatch,tmp_path)
    path=tmp_path/'script.py';path.write_text('original');path.chmod(0o750)
    before=stat.S_IMODE(path.stat().st_mode)
    txid=repair.begin_transaction('repair','low',{'script.py':'original'},[])
    repair.write_candidate('script.py','candidate')
    assert stat.S_IMODE(path.stat().st_mode)==before
    repair.rollback(txid)
    assert path.read_text()=='original' and stat.S_IMODE(path.stat().st_mode)==before
