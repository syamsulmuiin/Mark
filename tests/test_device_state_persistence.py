"""Device metadata must not drift from disk after a failed update."""
import copy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.device_mesh import DeviceMesh


def paired_mesh(tmp_path):
    mesh = DeviceMesh(tmp_path)
    key = Ed25519PrivateKey.generate()
    request = mesh.create_pairing_request(dict(device_id='phone', name='Phone',
        public_key=mesh._b64(key.public_key().public_bytes_raw())))
    code = mesh.issue_pairing_code(request['pairing_id'])['code']
    payload = f"{request['pairing_id']}:{code}:{request['nonce']}".encode()
    mesh.claim_pairing_request(request['pairing_id'], code, mesh._b64(key.sign(payload)))
    return mesh


def update(mesh, operation):
    if operation == 'revoke':
        return mesh.revoke('phone')
    if operation == 'manifest':
        return mesh.set_capability_manifest('phone', {'jarvis.command': {'version': 2}})
    if operation == 'health':
        return mesh.record_capability_result('phone', 'jarvis.command', False, 100, 'offline')
    return mesh.touch('phone')


@pytest.mark.parametrize('operation', ['revoke', 'manifest', 'health', 'touch'])
def test_failed_update_preserves_memory_and_restart_state(tmp_path, monkeypatch, operation):
    mesh = paired_mesh(tmp_path)
    mesh.record_capability_result('phone', 'jarvis.command', True, verified=True)
    before = copy.deepcopy(mesh.get('phone'))
    disk = mesh.trust_path.read_bytes()
    monkeypatch.setattr('core.device_mesh.time.time', lambda: before['last_seen'] + 60)
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(mesh, '_atomic', fail)
    with pytest.raises(OSError):
        update(mesh, operation)
    assert mesh.get('phone') == before == DeviceMesh(tmp_path).get('phone')
    assert mesh.trust_path.read_bytes() == disk
    assert mesh.authorized('phone', 'jarvis.command')


@pytest.mark.parametrize('operation', ['revoke', 'manifest', 'health', 'touch'])
def test_committed_update_survives_restart(tmp_path, monkeypatch, operation):
    mesh = paired_mesh(tmp_path)
    before = copy.deepcopy(mesh.get('phone'))
    monkeypatch.setattr('core.device_mesh.time.time', lambda: before['last_seen'] + 60)
    update(mesh, operation)
    assert mesh.get('phone') != before
    assert mesh.get('phone') == DeviceMesh(tmp_path).get('phone')
    assert mesh.authorized('phone', 'jarvis.command') == (operation != 'revoke')


def test_replace_failure_cleans_temporary_state_and_keeps_trust(tmp_path, monkeypatch):
    mesh = paired_mesh(tmp_path)
    before = copy.deepcopy(mesh.get('phone'))
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr('core.device_mesh.os.replace', fail)
    with pytest.raises(OSError):
        mesh.revoke('phone')
    assert mesh.get('phone') == before == DeviceMesh(tmp_path).get('phone')
    assert not list(mesh.dir.glob('*.tmp'))


def test_failed_revocation_does_not_send_logout_to_companion(tmp_path, monkeypatch):
    import ast
    import asyncio
    from pathlib import Path
    from types import SimpleNamespace
    mesh = paired_mesh(tmp_path)
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(mesh, '_atomic', fail)
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'dashboard/server.py').read_text())
    handler = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.AsyncFunctionDef) and node.name == 'revoke_paired_device')
    handler.decorator_list = []
    handler.args.args.append(ast.arg(arg='self'))
    handler.args.args[1].annotation = None
    messages = []
    class Socket:
        async def close(self, **kwargs):
            messages.append(kwargs)
    socket = Socket()
    host = SimpleNamespace(_mesh=mesh, _device_sockets={'phone': socket})
    namespace = {'_auth': lambda req: True, 'JSONResponse': lambda value, **kw: value}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[handler], type_ignores=[])),
                 '<revocation endpoint>', 'exec'), namespace)
    with pytest.raises(OSError):
        asyncio.run(namespace['revoke_paired_device']('phone', None, host))
    assert messages == [] and host._device_sockets['phone'] is socket
    assert mesh.authorized('phone', 'jarvis.command')
