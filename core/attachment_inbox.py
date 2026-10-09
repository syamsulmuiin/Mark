"""Persistent, device-scoped attachment inbox referencing the shared SHA-256 object store."""
from __future__ import annotations
import json, os, secrets, time
from pathlib import Path


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

    def create(self, *, source_device, destination_device, name, sha256, size, assistant_upload=False, server_upload=False, source_path=""):

        now = time.time()
        item = dict(id=secrets.token_urlsafe(18), source_device=source_device,
                    destination_device=destination_device, name=name, sha256=sha256,
                    size=int(size), created_at=now,
                    assistant_upload=bool(assistant_upload), server_upload=bool(server_upload),
                    source_path=str(source_path or ""),
                    status="stored" if server_upload else "assistant_ready" if assistant_upload else "pending")
        self.items[item["id"]] = item
        self._save()
        return dict(item)

    def for_device(self, device_id):
        return sorted((dict(item) for item in self.items.values()
                       if item["destination_device"] == device_id and not item.get("assistant_upload")),
                      key=lambda x: x["created_at"], reverse=True)

    def sent_by(self, device_id):
        return sorted((dict(item) for item in self.items.values()
                       if item["source_device"] == device_id),
                      key=lambda x: x["created_at"], reverse=True)

    def get(self, device_id, attachment_id):
        item = self.items.get(attachment_id)
        if not item or item["destination_device"] != device_id:
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

    def referenced(self, digest):
        return any(item["sha256"] == digest for item in self.items.values())
