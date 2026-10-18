from pathlib import Path
import pytest
from core.attachment_inbox import AttachmentInbox
from core.file_store import ObjectStore


def setup(tmp_path):
    inbox=AttachmentInbox(tmp_path / 'metadata')
    store=ObjectStore(tmp_path / 'files')
    store.attachment_referenced=inbox.referenced
    source=tmp_path / 'source.txt'
    source.write_text('shared content')
    info=store.ingest(source,'paper.txt')
    item=inbox.create(source_device='sender',destination_device='recipient',name='paper.txt',
                      sha256=info['sha256'],size=info['size'])
    return inbox,store,item


def test_hide_is_device_scoped_persistent_and_retains_bytes(tmp_path):
    inbox,store,item=setup(tmp_path)
    inbox.manage('recipient',item['id'],'hide')
    restored=AttachmentInbox(inbox.path.parent)
    assert restored.for_device('recipient') == []
    assert len(restored.sent_by('sender')) == 1
    assert store.by_hash(item['sha256'])
    restored.manage('sender',item['id'],'hide')
    assert restored.sent_by('sender') == []
    assert restored.referenced(item['sha256'])


@pytest.mark.parametrize('action', ['hide','delete'])
def test_unrelated_device_cannot_manage_attachment(tmp_path,action):
    inbox,store,item=setup(tmp_path)
    before=inbox.path.read_bytes()
    with pytest.raises(PermissionError):inbox.manage('stranger',item['id'],action)
    assert inbox.path.read_bytes() == before and store.by_hash(item['sha256'])


def test_delete_removes_unshared_copy_and_survives_reload(tmp_path):
    inbox,store,item=setup(tmp_path)
    source=tmp_path / 'original.docx'
    source.write_text('original remains')
    inbox.manage('sender',item['id'],'delete')
    assert store.delete_attachment_copy(item['sha256'],item['name'])
    assert AttachmentInbox(inbox.path.parent).items == {}
    assert ObjectStore(store.root).by_hash(item['sha256']) is None
    assert source.read_text() == 'original remains'


def test_delete_preserves_another_recipients_copy(tmp_path):
    inbox,store,item=setup(tmp_path)
    other=inbox.create(source_device='sender',destination_device='other',name='paper.txt',sha256=item['sha256'],size=item['size'])
    inbox.manage('recipient',item['id'],'delete')
    assert not store.delete_attachment_copy(item['sha256'],item['name'])
    assert inbox.get('other',other['id']) and store.by_hash(item['sha256'])


def test_delete_preserves_another_alias_and_newer_same_name(tmp_path):
    inbox,store,item=setup(tmp_path)
    copy=tmp_path / 'copy.txt'; copy.write_text('shared content'); store.ingest(copy,'other.txt')
    replacement=tmp_path / 'replacement.txt'; replacement.write_text('new content'); new=store.ingest(replacement,'paper.txt')
    inbox.manage('recipient',item['id'],'delete')
    assert not store.delete_attachment_copy(item['sha256'],item['name'])
    assert store.resolve('paper.txt')['sha256'] == new['sha256']
    assert store.resolve('other.txt')['sha256'] == item['sha256']


def test_failed_hide_persistence_restores_memory(tmp_path,monkeypatch):
    inbox,store,item=setup(tmp_path)
    def fail():raise OSError('disk full')
    monkeypatch.setattr(inbox,'_save',fail)
    with pytest.raises(OSError):inbox.manage('recipient',item['id'],'hide')
    assert len(inbox.for_device('recipient')) == 1


def test_authenticated_websocket_management_updates_lists_and_storage(tmp_path):
    import ast
    import asyncio
    from types import SimpleNamespace
    inbox,store,item=setup(tmp_path)
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'dashboard/server.py').read_text())
    branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="msg.get('type') == 'attachment.manage'")
    function=ast.AsyncFunctionDef(name='invoke',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=x) for x in ['self','device_id','websocket','msg']],kwonlyargs=[],kw_defaults=[],defaults=[]),body=branch.body,decorator_list=[])
    namespace={'_interaction_event':lambda *args,**kwargs:None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'<attachment handler>','exec'),namespace)
    replies,refreshes=[],[]
    class Socket:
        async def send_json(self, message):replies.append(message)
    socket=Socket()
    async def refresh(ws,device):refreshes.append(device)
    runtime=SimpleNamespace(_attachment_inbox=inbox,_file_store=store,
                            _device_sockets={'sender':socket,'recipient':socket},
                            _send_attachment_inbox=refresh,_send_attachment_sent=refresh)
    asyncio.run(namespace['invoke'](runtime,'stranger',socket,{'id':item['id'],'action':'delete'}))
    assert replies[-1]['type']=='attachment.error' and inbox.items
    asyncio.run(namespace['invoke'](runtime,'recipient',socket,{'id':item['id'],'action':'delete'}))
    assert replies[-1]['type']=='attachment.managed' and replies[-1]['server_copy_removed'] is True
    assert set(refreshes)=={'sender','recipient'}
    assert not inbox.items and store.by_hash(item['sha256']) is None
