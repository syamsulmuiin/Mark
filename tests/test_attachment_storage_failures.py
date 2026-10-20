"""Storage failures must preserve committed metadata and recoverable bytes."""
import copy
import json

import pytest

from core.attachment_inbox import AttachmentInbox
from core.file_store import ObjectStore


def fail():
    raise OSError('disk full')


def create(inbox):
    return inbox.create(source_device='server', destination_device='phone',
                        name='paper.txt', sha256='a' * 64, size=5)


@pytest.mark.parametrize('content', ['{', '[]', '{"bad": {}}'])
def test_corrupt_inbox_is_not_silently_reset(tmp_path, content):
    path = tmp_path / 'attachments.json'
    path.write_text(content)
    with pytest.raises(ValueError):
        AttachmentInbox(tmp_path)
    assert path.read_text() == content


@pytest.mark.parametrize('content', ['{', '[]', '{}', '{"aliases": {}, "objects": []}'])
def test_corrupt_object_index_is_not_silently_reset(tmp_path, content):
    meta = tmp_path / 'metadata'
    meta.mkdir()
    path = meta / 'index.json'
    path.write_text(content)
    with pytest.raises(ValueError):
        ObjectStore(tmp_path)
    assert path.read_text() == content


def test_failed_create_and_mark_restore_committed_inbox(tmp_path, monkeypatch):
    inbox = AttachmentInbox(tmp_path)
    item = create(inbox)
    before = copy.deepcopy(inbox.items)
    monkeypatch.setattr(inbox, '_save', fail)
    with pytest.raises(OSError):
        create(inbox)
    assert inbox.items == before
    with pytest.raises(OSError):
        inbox.mark('phone', item['id'], 'saved')
    assert inbox.items == before == AttachmentInbox(tmp_path).items


def test_failed_ingest_preserves_source_previous_alias_and_memory(tmp_path, monkeypatch):
    store = ObjectStore(tmp_path / 'store')
    source = tmp_path / 'source.txt'
    source.write_text('old')
    previous = store.ingest(source, 'paper.txt')
    before = copy.deepcopy(store.index)
    source.write_text('new')
    monkeypatch.setattr(store, '_save', fail)
    with pytest.raises(OSError):
        store.ingest(source, 'paper.txt')
    assert source.read_text() == 'new'
    assert previous['path'].read_text() == 'old'
    assert store.index == before == ObjectStore(store.root).index


@pytest.mark.parametrize('temporary', [False, True])
def test_failed_deletion_keeps_object_and_metadata(tmp_path, monkeypatch, temporary):
    store = ObjectStore(tmp_path / 'store')
    source = tmp_path / 'source.txt'
    source.write_text('keep')
    obj = store.ingest(source, 'paper.txt', temporary=temporary)
    before = copy.deepcopy(store.index)
    monkeypatch.setattr(store, '_save', fail)
    with pytest.raises(OSError):
        if temporary:
            store.release_temporary(obj['sha256'])
        else:
            store.delete_attachment_copy(obj['sha256'], 'paper.txt')
    assert obj['path'].read_text() == 'keep'
    assert store.index == before == ObjectStore(store.root).index


def test_object_lookup_rejects_traversal_and_symlink(tmp_path):
    store = ObjectStore(tmp_path / 'store')
    outside = tmp_path / 'outside.txt'
    outside.write_text('private')
    assert store.by_hash('../../outside.txt') is None
    assert not store.delete_attachment_copy('../../outside.txt', 'paper.txt')
    (store.objects / ('a' * 64)).symlink_to(outside)
    assert store.by_hash('a' * 64) is None
    assert outside.read_text() == 'private'


def test_failed_atomic_replace_cleans_temporary_metadata(tmp_path, monkeypatch):
    import os
    inbox = AttachmentInbox(tmp_path)
    create(inbox)
    before = inbox.path.read_bytes()
    def reject(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(os, 'replace', reject)
    with pytest.raises(OSError):
        create(inbox)
    assert inbox.path.read_bytes() == before
    assert not list(tmp_path.glob('attachments-*.tmp'))
    assert len(json.loads(before)) == 1
