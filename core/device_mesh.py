"""Persistent device identity, pairing and capability authorization.

Each JARVIS installation owns an Ed25519 key. Trusted peers are stored separately
from conversational memory. Pairing proves possession of a peer private key;
permissions are explicit capabilities and are never implied by trust alone.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, socket, threading, time, uuid
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

    def create_pairing_request(self, peer: dict, ttl: int = 300) -> dict:
        """Create an opaque pending request; no pairing code is returned."""
        device_id = str(peer.get("device_id", "")).strip()
        public_key = str(peer.get("public_key", "")).strip()
        if not device_id or not public_key:
            raise ValueError("peer identity missing")
        now = int(time.time())
        pairing_id = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        record = {
            "pairing_id": pairing_id,
            "peer": {
                "device_id": device_id,
                "name": str(peer.get("name") or device_id),
                "public_key": public_key,
            },
            "nonce": nonce,
            "code_digest": None,
            "attempts": 0,
            "expires_at": now + int(ttl),
            "created_at": now,
            "claimed_at": None,
        }
        with self._lock:
            self._pending[pairing_id] = record
        return {
            "pairing_id": pairing_id,
            "nonce": nonce,
            "expires_at": record["expires_at"],
            "local": self.public_identity(),
        }

    def pending_requests(self):
        now = int(time.time())
        with self._lock:
            expired = [key for key, value in self._pending.items() if value.get("expires_at", 0) <= now]
            for key in expired:
                self._pending.pop(key, None)
            return [
                {
                    "pairing_id": value["pairing_id"],
                    "device_id": value["peer"]["device_id"],
                    "name": value["peer"]["name"],
                    "expires_at": value["expires_at"],
                    "code_issued": bool(value.get("code_digest")),
                }
                for value in self._pending.values()
            ]

    def issue_pairing_code(self, pairing_id: str) -> dict:
        with self._lock:
            record = self._pending.get(str(pairing_id or ""))
            if not record or record.get("claimed_at") is not None:
                raise ValueError("pairing_not_found_or_used")
            if record["expires_at"] <= int(time.time()):
                self._pending.pop(record["pairing_id"], None)
                raise ValueError("pairing_expired")
            code_chars = [
                secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"),
                secrets.choice("23456789"),
                *(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6)),
            ]
            secrets.SystemRandom().shuffle(code_chars)
            code = "".join(code_chars)
            record["code_digest"] = hashlib.sha256(code.encode()).hexdigest()
            record["issued_at"] = int(time.time())
            record["attempts"] = 0
            return {"pairing_id": record["pairing_id"], "code": code, "expires_at": record["expires_at"], "device_id": record["peer"]["device_id"]}

    def claim_pairing_request(self, pairing_id: str, code: str, signature: str, capabilities=None) -> dict:
        pairing_id = str(pairing_id or "")
        code = str(code or "").strip().upper()
        with self._lock:
            record = self._pending.get(pairing_id)
            if not record or record.get("claimed_at") is not None:
                raise ValueError("pairing_not_found_or_used")
            if record["expires_at"] <= int(time.time()):
                self._pending.pop(pairing_id, None)
                raise ValueError("pairing_expired")
            if not record.get("code_digest"):
                raise ValueError("pairing_code_not_issued")
            if record.get("attempts", 0) >= 5:
                self._pending.pop(pairing_id, None)
                raise ValueError("pairing_locked")
            digest = hashlib.sha256(code.encode()).hexdigest()
            if not hmac.compare_digest(record["code_digest"], digest):
                record["attempts"] = int(record.get("attempts", 0)) + 1
                if record["attempts"] >= 5:
                    self._pending.pop(pairing_id, None)
                raise ValueError("pairing_code_invalid")
            peer = record["peer"]
            payload = f"{pairing_id}:{code}:{record['nonce']}".encode()
            if not self.verify(peer["public_key"], payload, signature):
                raise ValueError("peer_signature_invalid")
            rec = {
                "device_id": peer["device_id"],
                "name": peer["name"],
                "public_key": peer["public_key"],
                "capabilities": sorted(set(capabilities or DEFAULT_CAPABILITIES)),
                "paired_at": int(time.time()),
                "last_seen": int(time.time()),
                "revoked": False,
            }
            self._trusted[peer["device_id"]] = rec
            self._atomic(self.trust_path, self._trusted)
            self._pending.pop(pairing_id, None)
            return dict(rec)

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

    def set_capability_manifest(self, device_id, manifest):
        """Persist non-authoritative capability metadata reported by a companion.

        Authorization still comes exclusively from the capability name allowlist;
        manifest metadata only informs routing/diagnostics and cannot grant access.
        """
        with self._lock:
            if device_id not in self._trusted: raise KeyError(device_id)
            clean={}
            if isinstance(manifest,dict):
                for name,meta in manifest.items():
                    name=str(name).strip()
                    if not name or name not in self._trusted[device_id].get("capabilities",[]):continue
                    clean[name]=dict(meta) if isinstance(meta,dict) else {}
            self._trusted[device_id]["capability_manifest"]=clean
            self._atomic(self.trust_path,self._trusted);return clean

    def record_capability_result(self, device_id, capability, success, latency_ms=0, error="", *, verified=None):
        """Record execution health separately from post-condition verification.

        UNVERIFIED is a successful execution whose external post-condition has not
        yet been observed; it must not poison device routing as a transport/action
        failure. Verification coverage is tracked independently.
        """
        with self._lock:
            rec=self._trusted.get(device_id)
            if not rec:return None
            health=rec.setdefault("capability_health",{}).setdefault(str(capability),{
                "success_count":0,"failure_count":0,"verified_count":0,"unverified_count":0,
                "avg_latency_ms":0.0,"health":"healthy","last_error":""})
            key="success_count" if success else "failure_count";health[key]=int(health.get(key,0))+1
            if success and verified is not None:
                vkey="verified_count" if bool(verified) else "unverified_count"
                health[vkey]=int(health.get(vkey,0))+1
            total=int(health.get("success_count",0))+int(health.get("failure_count",0))
            if latency_ms:
                prev=max(0,total-1);health["avg_latency_ms"]=((float(health.get("avg_latency_ms",0))*prev)+float(latency_ms))/max(1,total)
            if error and not success:health["last_error"]=str(error)[:500]
            elif success:health["last_error"]=""
            if int(health.get("failure_count",0))>=3 and int(health.get("failure_count",0))>int(health.get("success_count",0)):health["health"]="degraded"
            if success and health.get("health")=="degraded" and int(health.get("success_count",0))>=int(health.get("failure_count",0)):health["health"]="healthy"
            self._atomic(self.trust_path,self._trusted);return dict(health)

    def revoke(self, device_id):
        with self._lock:
            if device_id in self._trusted:
                self._trusted[device_id]["revoked"] = True; self._atomic(self.trust_path, self._trusted); return True
        return False
    def touch(self, device_id):
        with self._lock:
            if device_id in self._trusted:
                self._trusted[device_id]["last_seen"] = int(time.time()); self._atomic(self.trust_path, self._trusted)
