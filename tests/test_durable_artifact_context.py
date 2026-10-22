import hashlib
from types import SimpleNamespace
from core import tool_feedback as mod
from core.attachment_inbox import AttachmentInbox


def test_restart_recovers_latest_revision_for_original_device(monkeypatch, tmp_path):
    root = tmp_path / 'artifacts'
    root.mkdir()
    monkeypatch.setattr(mod, 'ARTIFACT_ROOT', root)
    metadata = tmp_path / 'metadata'
    inbox = AttachmentInbox(metadata)
    for name, content in [('original.csv', '85000'), ('revised.csv', '105000')]:
        path = root / name
        path.write_text(content)
        inbox.create(source_device='server', destination_device='phone', name=name,
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size,
                     source_path=str(path))
    restarted = SimpleNamespace(_attachment_inbox=AttachmentInbox(metadata))
    records = mod.durable_artifacts(restarted, 'phone')
    assert [r['name'] for r in records] == ['revised.csv', 'original.csv']
    assert records[0]['file_path'] == str(root / 'revised.csv')
    assert mod.durable_artifacts(restarted, 'other-phone') == []
    assert mod.durable_artifacts(restarted, 'local') == []


def test_changed_missing_deleted_and_symlinked_artifacts_are_not_recovered(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'ARTIFACT_ROOT', tmp_path)
    inbox = AttachmentInbox(tmp_path / 'metadata')
    ids = {}
    for name in ('changed.csv', 'missing.csv', 'deleted.csv', 'link.csv'):
        path = tmp_path / name
        path.write_text('original')
        item = inbox.create(source_device='server', destination_device='phone', name=name,
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=8, source_path=str(path))
        ids[name] = item['id']
    (tmp_path / 'changed.csv').write_text('modified')
    (tmp_path / 'missing.csv').unlink()
    inbox.manage('phone', ids['deleted.csv'], 'delete')
    (tmp_path / 'link.csv').unlink()
    (tmp_path / 'link.csv').symlink_to(tmp_path / 'deleted.csv')
    assert mod.durable_artifacts(SimpleNamespace(_attachment_inbox=inbox), 'phone') == []


def test_real_export_relative_metadata_survives_restart_and_changed_cwd(monkeypatch, tmp_path):
    from core.server_export_policy import approve_server_export
    project = tmp_path / 'project'
    root = project / 'storage' / 'artifacts'
    root.mkdir(parents=True)
    monkeypatch.setattr(mod, 'ARTIFACT_ROOT', root)
    monkeypatch.setattr(mod, 'BASE_DIR', project)
    path = root / 'report.csv'
    path.write_text('Pena,5,10000,50000\nTotal,105000')
    approved = approve_server_export(str(path), base_dir=project)
    assert approved.source_path == 'storage/artifacts/report.csv'
    metadata = tmp_path / 'metadata'
    inbox = AttachmentInbox(metadata)
    inbox.create(source_device='server', destination_device='phone', name=path.name,
                 sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size,
                 source_path=approved.source_path)
    monkeypatch.chdir(tmp_path)
    restarted = SimpleNamespace(_attachment_inbox=AttachmentInbox(metadata))
    result = mod.durable_artifacts(restarted, 'phone')
    assert result[0]['file_path'] == str(path)
    assert result[0]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert mod.durable_artifacts(restarted, 'foreign') == []


def test_relative_metadata_cannot_escape_artifact_root(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(mod, 'ARTIFACT_ROOT', tmp_path / 'artifacts')
    secret = tmp_path / 'private.txt'
    secret.write_text('private')
    data = {'source_device': 'server', 'destination_device': 'phone', 'source_path': 'private.txt',
            'created_at': 0, 'sha256': hashlib.sha256(secret.read_bytes()).hexdigest()}
    host = SimpleNamespace(_attachment_inbox=SimpleNamespace(items={'one': data}))
    assert mod.durable_artifacts(host, 'phone') == []
