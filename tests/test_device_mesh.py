import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.device_mesh import DeviceMesh


def peer():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes_raw()
    return key, {
        "device_id": "phone-1",
        "name": "Test phone",
        "public_key": DeviceMesh._b64(public),
    }


def test_pairing_request_does_not_return_or_store_code(tmp_path):
    mesh = DeviceMesh(tmp_path)
    _, identity = peer()

    result = mesh.create_pairing_request(identity, ttl=300)

    assert result["pairing_id"]
    assert "code" not in result
    assert all("code" not in item for item in mesh.pending_requests())


def test_operator_issued_code_is_one_time_and_claim_requires_request(tmp_path):
    mesh = DeviceMesh(tmp_path)
    key, identity = peer()
    request = mesh.create_pairing_request(identity, ttl=300)

    issued = mesh.issue_pairing_code(request["pairing_id"])
    assert len(issued["code"]) == 8
    assert issued["code"] not in mesh.pending_requests()[0].values()

    payload = f'{request["pairing_id"]}:{issued["code"]}:{request["nonce"]}'.encode()
    signature = DeviceMesh._b64(key.sign(payload))
    claimed = mesh.claim_pairing_request(request["pairing_id"], issued["code"], signature)

    assert claimed["device_id"] == "phone-1"
    with pytest.raises(ValueError, match="pairing_not_found_or_used"):
        mesh.claim_pairing_request(request["pairing_id"], issued["code"], signature)


def test_unknown_pairing_id_cannot_issue_code(tmp_path):
    mesh = DeviceMesh(tmp_path)
    with pytest.raises(ValueError, match="pairing_not_found_or_used"):
        mesh.issue_pairing_code("unknown")
