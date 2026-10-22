import ast
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
from actions import file_processor


def test_csv_inspection_reads_exact_values_without_model_or_pandas(monkeypatch, tmp_path):
    from core import artifact_paths
    monkeypatch.setattr(artifact_paths, 'BASE_DIR', tmp_path)
    root = tmp_path / 'storage' / 'artifacts'
    root.mkdir(parents=True)
    path = root / 'report.csv'
    path.write_text('Buku,3,45000\nPena,5,50000\nTas,2,50000\nTotal,145000')
    monkeypatch.setattr(file_processor, '_gemini_client', lambda: (_ for _ in ()).throw(AssertionError('must not call a model')))
    data = json.loads(file_processor.file_processor({'action': 'inspect', 'file_path': str(path)}))
    assert data['verified'] is True
    assert data['content'] == path.read_text()
    assert data['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert data['verification_scope'] == 'source_readback_only'


def test_inspection_denies_private_path_and_reports_large_source(monkeypatch, tmp_path):
    from core import artifact_paths
    monkeypatch.setattr(artifact_paths, 'BASE_DIR', tmp_path)
    secret = tmp_path / 'private.json'
    secret.write_text('{"private":true}')
    data = json.loads(file_processor.file_processor({'action': 'inspect', 'file_path': str(secret)}))
    assert data['status'] == 'FAILED'
    assert 'content' not in data
    root = tmp_path / 'storage'
    root.mkdir()
    large = root / 'large.csv'
    large.write_text('x' * 8001)
    data = json.loads(file_processor.file_processor({'action': 'inspect', 'file_path': str(large)}))
    assert data['reason'] == 'inspection_requires_bounded_analysis'
    assert data['verified'] is False


def test_misrouted_csv_keeps_function_identity_and_file_policy():
    source = Path(__file__).parents[1] / 'main.py'
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'JarvisLive')
    method = next(n for n in cls.body if getattr(n, 'name', '') == '_execute_tool')
    namespace = {'types': NS(FunctionResponse=lambda **kw: NS(**kw)), 'Path': Path, '_trace_event': lambda *a, **kw: None}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    calls = []
    async def guarded(fc):
        calls.append(fc)
        return NS(response={'outcome': 'BLOCKED', 'approval_required': True})
    host = NS(_dashboard=None, ui=NS(set_state=lambda *a: None), _execute_tool=guarded)
    request = NS(id='one', name='document_editor', args={'action': 'inspect', 'file_path': '/private/report.csv'})
    response = asyncio.run(namespace['_execute_tool'](host, request))
    assert response.name == 'document_editor' and response.id == 'one'
    assert calls[0].name == 'file_processor'
    assert calls[0].args['file_path'] == '/private/report.csv'
    assert response.response['outcome'] == 'BLOCKED'
