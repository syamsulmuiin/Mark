from pathlib import Path

from core import repair_engine as repair


def test_validation_copy_excludes_live_credentials_but_retains_source(tmp_path,monkeypatch):
    repo=tmp_path/'repo'; repo.mkdir()
    for name in ['devices/identity.json','devices/local_api.token','config/provider_auth/openai_codex.json',
                 'config/api_keys.json','config/credentials.json','config/token.json','.env','private.pem','runtime/error.log']:
        file=repo/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_text('private')
    for name in ['main.py','core/example.py','config/__init__.py','tests/test_example.py','desktop-companion/runtime/core/model_config.py']:
        file=repo/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_text('# source')
    monkeypatch.setattr(repair,'BASE_DIR',repo)
    def validate(root,candidates,timeout):
        assert not (root/'devices').exists() and not (root/'runtime').exists()
        assert (root/'desktop-companion/runtime/core/model_config.py').read_text()=='# source'
        assert not (root/'config/provider_auth').exists()
        assert not (root/'config/api_keys.json').exists()
        assert not (root/'config/credentials.json').exists()
        assert not (root/'config/token.json').exists()
        assert not (root/'.env').exists() and not (root/'private.pem').exists()
        assert (root/'config/__init__.py').exists() and (root/'tests/test_example.py').exists()
        assert (root/'core/example.py').read_text()=='# candidate'
        return True,[]
    monkeypatch.setattr(repair,'_run_validators',validate)
    assert repair.validate_sandbox({'core/example.py':'# candidate'})==(True,[])
    assert (repo/'devices/identity.json').read_text()=='private'
