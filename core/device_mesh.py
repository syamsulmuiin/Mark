"""Persistent device identity, pairing and capability authorization.

Each JARVIS installation owns an Ed25519 key. Trusted peers are stored separately
from conversational memory. Pairing proves possession of a peer private key;
permissions are explicit capabilities and are never implied by trust alone.
"""
from __future__ import annotations
import base64, hashlib, json, os, secrets, socket, threading, time, uuid
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

DEFAULT_CAPABILITIES = ["jarvis.command", "notifications.receive"]

class DeviceMesh:
    def __init__(self, base_dir: Path):
        self.dir = Path(base_dir) / "devices"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.identity_path = self.dir / "identity.json"
        self.trust_path = self.dir / "trusted_devices.json"
        self._lock = threading.RLock()
        self._pending = {}
        self._identity = self._load_identity()
        self._trusted = self._load_json(self.trust_path, {})

    @staticmethod
    def _b64(b: bytes) -> str: return base64.urlsafe_b64encode(b).decode().rstrip("=")
    @staticmethod
    def _unb64(s: str) -> bytes: return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    @staticmethod
    def _load_json(path, default):
        try: return json.loads(path.read_text(encoding="utf-8"))
        except Exception: return default
    def _atomic(self, path, data):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def _load_identity(self):
        d = self._load_json(self.identity_path, None)
        if d and d.get("private_key") and d.get("device_id"): return d
        key = Ed25519PrivateKey.generate()
        raw_priv = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        raw_pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        d = {"device_id": str(uuid.uuid4()), "name": socket.gethostname() or "JARVIS",
             "private_key": self._b64(raw_priv), "public_key": self._b64(raw_pub), "created_at": int(time.time())}
        self._atomic(self.identity_path, d)
        try: os.chmod(self.identity_path, 0o600)
        except Exception: pass
        return d

    @property
    def device_id(self): return self._identity["device_id"]
    @property
    def public_key(self): return self._identity["public_key"]
    @property
    def name(self): return self._identity["name"]
    def public_identity(self): return {"device_id": self.device_id, "name": self.name, "public_key": self.public_key}
    def _private(self): return Ed25519PrivateKey.from_private_bytes(self._unb64(self._identity["private_key"]))
    def sign(self, payload: bytes): return self._b64(self._private().sign(payload))
    @classmethod
    def verify(cls, public_key: str, payload: bytes, signature: str):
        try:
            Ed25519PublicKey.from_public_bytes(cls._unb64(public_key)).verify(cls._unb64(signature), payload); return True
        except Exception: return False

    def create_pairing_offer(self, ttl=600):
        now, nonce = int(time.time()), secrets.token_urlsafe(24)
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        offer = {**self.public_identity(), "nonce": nonce, "code": code, "expires_at": now + int(ttl)}
        canonical = json.dumps(offer, sort_keys=True, separators=(",", ":")).encode()
        offer["signature"] = self.sign(canonical)
        with self._lock: self._pending[code] = {"nonce": nonce, "expires_at": offer["expires_at"], "offer": dict(offer)}
        return offer

    def pending_offer(self, code):
        code = str(code or "").upper()
        with self._lock:
            pending = self._pending.get(code)
            if not pending or pending["expires_at"] < time.time():
                self._pending.pop(code, None)
                return None
            return dict(pending.get("offer") or {})

    def accept_pairing(self, code, peer, signature, capabilities=None, replace_device_ids=None):
        with self._lock: pending = self._pending.pop(str(code).upper(), None)
        if not pending or pending["expires_at"] < time.time(): raise ValueError("pairing code invalid or expired")
        required = (pending["nonce"] + ":" + str(code).upper()).encode()
        if not self.verify(peer.get("public_key", ""), required, signature): raise ValueError("peer signature verification failed")
        did = str(peer.get("device_id", "")).strip()
        if not did: raise ValueError("peer device_id missing")
        caps = sorted(set(capabilities or DEFAULT_CAPABILITIES))
        rec = {"device_id": did, "name": str(peer.get("name") or did), "public_key": peer["public_key"],
               "capabilities": caps, "paired_at": int(time.time()), "last_seen": int(time.time()), "revoked": False}
        replaced = []
        with self._lock:
            for old_id in sorted(set(map(str, replace_device_ids or []))):
                if old_id != did and old_id in self._trusted:
                    self._trusted.pop(old_id, None)
                    replaced.append(old_id)
            self._trusted[did] = rec
            self._atomic(self.trust_path, self._trusted)
        result = dict(rec)
        result["replaced_device_ids"] = replaced
        return result

    def list_devices(self):
        with self._lock: return [{k:v for k,v in r.items() if k != "public_key"} for r in self._trusted.values()]
    def get(self, device_id): return self._trusted.get(device_id)
    def authorized(self, device_id, capability):
        r=self._trusted.get(device_id); return bool(r and not r.get("revoked") and capability in r.get("capabilities", []))
    def set_capabilities(self, device_id, capabilities):
        with self._lock:
            if device_id not in self._trusted: raise KeyError(device_id)
            self._trusted[device_id]["capabilities"] = sorted(set(map(str, capabilities)))
            self._atomic(self.trust_path, self._trusted); return self._trusted[device_id]
    def revoke(self, device_id):
        with self._lock:
            if device_id in self._trusted:
                self._trusted[device_id]["revoked"] = True; self._atomic(self.trust_path, self._trusted); return True
        return False
    def touch(self, device_id):
        with self._lock:
            if device_id in self._trusted:
                self._trusted[device_id]["last_seen"] = int(time.time()); self._atomic(self.trust_path, self._trusted)
