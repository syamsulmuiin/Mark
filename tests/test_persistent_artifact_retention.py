from pathlib import Path

from core.attachment_inbox import AttachmentInbox
from core.file_store import ObjectStore


def test_attachment_inbox_is_durable_without_time_expiry(tmp_path, monkeypatch):
    inbox = AttachmentInbox(tmp_path / "meta")
    item = inbox.create(source_device="server", destination_device="phone", name="report.pdf", sha256="a" * 64, size=42)
    assert "expires_at" not in item

    monkeypatch.setattr("core.attachment_inbox.time.time", lambda: 10**12)
    assert inbox.get("phone", item["id"])["name"] == "report.pdf"
    assert inbox.for_device("phone")[0]["id"] == item["id"]
    assert inbox.referenced("a" * 64)


def test_durable_attachment_reference_protects_object(tmp_path):
    store = ObjectStore(tmp_path / "storage")
    inbox = AttachmentInbox(store.meta)
    store.attachment_referenced = inbox.referenced
    source = tmp_path / "upload.bin"
    source.write_bytes(b"persistent user data")
    info = store.ingest(source, "upload.bin", temporary=True)
    inbox.create(source_device="phone", destination_device="desktop", name="upload.bin", sha256=info["sha256"], size=info["size"])

    assert store.release_temporary(info["sha256"]) is False
    assert store.by_hash(info["sha256"])["path"].is_file()


def test_transfer_and_server_artifact_ingest_are_durable_by_default():
    server = Path("dashboard/server.py").read_text(encoding="utf-8")
    transfer = server[server.index("    async def transfer_file("):server.index("    async def send_server_file(")]
    send = server[server.index("    async def send_server_file("):server.index("    async def _send_attachment_inbox")]
    gc = server[server.index("    def _release_expired_attachments("):server.index("    async def _attachment_gc_loop")]

    assert 'temporary=False, server_storage=server_storage' in transfer
    assert 'ingest(tmp, name, temporary=False)' in send
    assert '.expire()' not in gc
    assert 'task_inputs' not in gc
