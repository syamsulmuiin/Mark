from pathlib import Path
import pytest

from core.server_export_policy import approve_server_export, validate_delivery_name
from core.attachment_inbox import AttachmentInbox


def test_runtime_and_storage_are_trusted_export_roots(tmp_path):
    runtime = tmp_path / "runtime"
    storage = tmp_path / "storage" / "reports"
    runtime.mkdir(parents=True)
    storage.mkdir(parents=True)
    interaction = runtime / "interaction.log"
    report = storage / "report.json"
    interaction.write_text("runtime evidence", encoding="utf-8")
    report.write_text('{"ok": true}', encoding="utf-8")

    a = approve_server_export(interaction, base_dir=tmp_path)
    b = approve_server_export(report, base_dir=tmp_path)
    assert a.source_path == "runtime/interaction.log"
    assert b.source_path == "storage/reports/report.json"


def test_project_source_cannot_be_disguised_as_log(tmp_path):
    (tmp_path / "runtime").mkdir()
    (tmp_path / "storage").mkdir()
    source = tmp_path / "main.py"
    source.write_text("print('not a log')", encoding="utf-8")
    with pytest.raises(PermissionError):
        approve_server_export(source, base_dir=tmp_path)


def test_symlink_escape_from_trusted_root_is_rejected(tmp_path):
    runtime = tmp_path / "runtime"
    storage = tmp_path / "storage"
    runtime.mkdir(); storage.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = runtime / "interaction.log"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(PermissionError):
        approve_server_export(link, base_dir=tmp_path)


def test_relative_traversal_cannot_escape_trusted_roots(tmp_path):
    (tmp_path / "runtime").mkdir()
    (tmp_path / "storage").mkdir()
    source = tmp_path / "core.py"
    source.write_text("source", encoding="utf-8")
    with pytest.raises(PermissionError):
        approve_server_export("runtime/../core.py", base_dir=tmp_path)


def test_generic_export_blocks_key_material_even_inside_storage(tmp_path):
    (tmp_path / "runtime").mkdir()
    storage = tmp_path / "storage"
    storage.mkdir()
    key = storage / "private.key"
    key.write_text("private", encoding="utf-8")
    with pytest.raises(PermissionError):
        approve_server_export(key, base_dir=tmp_path)


def test_delivery_rename_must_preserve_file_type(tmp_path):
    source = tmp_path / "result.py"
    assert validate_delivery_name(source, "renamed.py") == "renamed.py"
    with pytest.raises(PermissionError):
        validate_delivery_name(source, "interaction.log")
    with pytest.raises(PermissionError):
        validate_delivery_name(tmp_path / "result.json", "error.log")


def test_attachment_persists_canonical_source_provenance(tmp_path):
    inbox = AttachmentInbox(tmp_path)
    item = inbox.create(source_device="server", destination_device="phone",
                        name="interaction.log", sha256="a" * 64, size=12,
                        source_path="runtime/interaction.log")
    restored = AttachmentInbox(tmp_path).get("phone", item["id"])
    assert restored["source_path"] == "runtime/interaction.log"
    assert restored["sha256"] == "a" * 64
    assert restored["size"] == 12
