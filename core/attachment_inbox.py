"""Persistent, device-scoped attachment inbox referencing the shared SHA-256 object store."""
from __future__ import annotations
import json, os, secrets, time
from pathlib import Path

RETENTION_SECONDS = 30 * 86400

class AttachmentInbox:
    def __init__(self, metadata_dir: Path):
        self.path = Path(metadata_dir) / "attachments.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            self.items = {}

    def _save(self):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def create(self, *, source_device, destination_device, name, sha256, size, assistant_upload=False, server_upload=False):
        now = time.time()
        item = dict(id=secrets.token_urlsafe(18), source_device=source_device,
                    destination_device=destination_device, name=name, sha256=sha256,
                    size=int(size), created_at=now, expires_at=now+RETENTION_SECONDS,
                    assistant_upload=bool(assistant_upload), server_upload=bool(server_upload),
                    status="stored" if server_upload else "assistant_ready" if assistant_upload else "pending")
        self.items[item["id"]] = item
        self._save()
        return dict(item)

    def for_device(self, device_id):
        now = time.time()
        return sorted((dict(item) for item in self.items.values()
                       if item["destination_device"] == device_id and not item.get("assistant_upload") and item["expires_at"] > now),
                      key=lambda x: x["created_at"], reverse=True)

    def sent_by(self, device_id):
        now = time.time()
        return sorted((dict(item) for item in self.items.values()
                       if item["source_device"] == device_id and item["expires_at"] > now),
                      key=lambda x: x["created_at"], reverse=True)

    def get(self, device_id, attachment_id):
        item = self.items.get(attachment_id)
        if not item or item["destination_device"] != device_id or item["expires_at"] <= time.time():
            return None
        return dict(item)

    def mark(self, device_id, attachment_id, status):
        if status not in ("delivered", "saved"):
            raise ValueError("Invalid attachment status")
        item = self.get(device_id, attachment_id)
        if item:
            self.items[attachment_id]["status"] = status
            self._save()
        return item is not None

    def expire(self):
        now = time.time()
        expired = [key for key, item in self.items.items() if item["expires_at"] <= now]
        for key in expired:
            del self.items[key]
        if expired:
            self._save()
        return expired

    def referenced(self, digest):
        return any(item["sha256"] == digest and item["expires_at"] > time.time()
                   for item in self.items.values())
