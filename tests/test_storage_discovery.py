import pytest
from core.server_export_policy import list_server_directory
from core.action_policy import requires_confirmation
from core.host_capabilities import capability_instruction


def test_storage_listing_all_formats_pagination_and_safety(tmp_path):
    storage = tmp_path / 'storage'
    storage.mkdir()
    for name in ['report.docx', 'data.csv', 'picture.webp', 'credentials.json', 'private.pem']:
        (storage / name).write_text('data')
    (storage / 'nested').mkdir()
    (storage / 'escape').symlink_to(tmp_path)
    (storage / 'secret-link.txt').symlink_to(storage / 'credentials.json')
    result = list_server_directory(base_dir=tmp_path, limit=2)
    second = list_server_directory(base_dir=tmp_path, offset=result['next_offset'], limit=2)
    assert result['total'] == 4
    assert {item['name'] for item in result['entries'] + second['entries']} == {'report.docx', 'data.csv', 'picture.webp', 'nested'}
    assert second['next_offset'] is None
    assert not requires_confirmation('file_processor', {'action': 'list_directory', 'file_path': str(storage)})
    assert list_server_directory('storage/nested', base_dir=tmp_path)['entries'] == []


def test_listing_cannot_escape_after_approval(tmp_path):
    (tmp_path / 'storage').mkdir()
    (tmp_path / 'storage' / 'outside').symlink_to(tmp_path)
    for path in ['.', 'storage/..', 'storage/outside']:
        with pytest.raises(PermissionError):
            list_server_directory(path, base_dir=tmp_path)


def test_file_processor_lists_without_loading_a_model(monkeypatch, tmp_path):
    from actions.file_processor import file_processor
    import core.artifact_paths
    import json
    monkeypatch.setattr(core.artifact_paths, 'BASE_DIR', tmp_path)
    (tmp_path / 'storage').mkdir()
    (tmp_path / 'storage' / 'report.pdf').write_bytes(b'pdf')
    result = json.loads(file_processor({'action': 'list_directory', 'file_path': 'storage'}))
    assert result['entries'][0]['name'] == 'report.pdf'
    rejected = json.loads(file_processor({'action': 'list_directory', 'file_path': str(tmp_path)}))
    assert rejected['status'] == 'FAILED'


def test_reasoning_capabilities_include_executable_skill_and_storage_routes():
    prompt = capability_instruction(['skill_manager', 'file_processor'])
    assert 'operation=ensure' in prompt
    assert 'action=list_directory' in prompt
