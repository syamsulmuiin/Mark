import hashlib
import json
from types import SimpleNamespace
from actions import file_processor as mod
from core import tool_feedback
from core.attachment_inbox import AttachmentInbox


def test_analysis_preserves_source_values_and_revision_instruction(monkeypatch, tmp_path):
    path = tmp_path / 'source.csv'
    path.write_text('Item,Quantity,Price,Subtotal\nBuku,2,15000,30000\nPena,5,10000,50000\nTas,1,25000,25000\nTotal,,,105000')
    import sys
    class Columns(list):
        pass
    class Frame:
        columns = Columns(['Item', 'Quantity', 'Price', 'Subtotal'])
        def __len__(self): return 4
        def head(self, count): return self
        def to_string(self): return 'Buku 2 15000 30000\nPena 5 10000 50000\nTas 1 25000 25000\nTotal 105000'
    monkeypatch.setitem(sys.modules, 'pandas', SimpleNamespace(read_csv=lambda *a, **kw: Frame()))
    prompts = []
    def generate(prompt):
        prompts.append(prompt)
        return SimpleNamespace(text='A summary that omits quantities')
    monkeypatch.setattr(mod, '_gemini_client', lambda: SimpleNamespace(generate_content=generate))
    data = json.loads(mod._process_data(path, 'csv', 'analyze', {'instruction': 'Change Buku quantity to 3; preserve the rest.'}))
    assert 'Change Buku quantity to 3' in prompts[0]
    assert 'Pena' in data['source_preview'] and '50000' in data['source_preview']
    assert data['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert data['verification_scope'] == 'source_readback_only_not_analysis_correctness'
    monkeypatch.setattr(tool_feedback, 'ARTIFACT_ROOT', tmp_path)
    evidence = tool_feedback.artifact_feedback('file_processor', data, {'action': 'analyze'})
    assert 'Pena,5,10000,50000' in evidence['artifact_readback']['content']


def test_recovered_revision_chain_exposes_original_and_preserved_change(monkeypatch, tmp_path):
    monkeypatch.setattr(tool_feedback, 'ARTIFACT_ROOT', tmp_path)
    inbox = AttachmentInbox(tmp_path / 'metadata')
    versions = [('initial.csv','Buku,2\nPena,3'), ('first_revision.csv','Buku,2\nPena,5'),
                ('incorrect_revision.csv','Buku,3\nPena,3')]
    for name, content in versions:
        path = tmp_path / name
        path.write_text(content)
        inbox.create(source_device='server', destination_device='phone', name=name,
                     sha256=hashlib.sha256(path.read_bytes()).hexdigest(), size=path.stat().st_size, source_path=str(path))
    records = tool_feedback.durable_artifacts(SimpleNamespace(_attachment_inbox=inbox), 'phone')
    assert records[0]['source_content'] == 'Buku,3\nPena,3'
    assert records[1]['source_content'] == 'Buku,2\nPena,5'
    assert records[2]['source_content'] == 'Buku,2\nPena,3'
