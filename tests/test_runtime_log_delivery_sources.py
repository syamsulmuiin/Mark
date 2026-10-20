"""Diagnostics must distinguish real attachment sources from an inspection."""
import json
from actions import runtime_diagnostics as mod


def sources(report):
    return json.loads(report.split("Log attachment sources (JSON):\n", 1)[1].split("\n", 1)[0])


def test_existing_logs_offer_current_device_attachment_handoff(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "RUNTIME_DIR", tmp_path)
    (tmp_path / "error.log").write_text("warning")
    (tmp_path / "interaction.log").write_text('{"event":"tool_started"}')
    report = mod.collect_runtime_evidence()
    assert sources(report) == [
        {"source": str(tmp_path / name), "destination_name": name}
        for name in ("error.log", "interaction.log")]
    assert "has not sent any file" in report
    assert "destination_device=current" in report
    assert "save_direct=false" in report


def test_missing_or_symlinked_logs_are_not_attachment_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "RUNTIME_DIR", tmp_path)
    secret = tmp_path / "private.txt"
    secret.write_text("private")
    (tmp_path / "error.log").symlink_to(secret)
    assert sources(mod.collect_runtime_evidence()) == []


def test_scope_does_not_offer_an_unrequested_log(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "RUNTIME_DIR", tmp_path)
    for name in ("error.log", "interaction.log"):
        (tmp_path / name).write_text("entry")
    assert [x["destination_name"] for x in sources(mod.collect_runtime_evidence("error"))] == ["error.log"]
