import importlib
from pathlib import Path


def test_activity_survives_reload_and_is_searchable(tmp_path, monkeypatch):
    import memory.activity_journal as journal
    monkeypatch.setattr(journal, "PATH", tmp_path / "journal.jsonl")
    journal.append("user", "Buatkan makalah tentang ketahanan pangan")
    journal.append("assistant", "Makalah sudah dibuat dan dikirim ke HP.")
    assert journal.PATH.exists()
    hits = journal.search("makalah", 8)
    assert len(hits) == 2
    assert "makalah" in hits[0]["text"].lower()
    ctx = journal.recent_context(8)
    assert "RECENT DURABLE ACTIVITY" in ctx
    assert "makalah" in ctx.lower()


def test_credentials_are_redacted_from_durable_activity(tmp_path, monkeypatch):
    import memory.activity_journal as journal
    monkeypatch.setattr(journal, "PATH", tmp_path / "journal.jsonl")
    journal.append("user", "password: secret123")
    raw = journal.PATH.read_text(encoding="utf-8")
    assert "secret123" not in raw
    assert "[REDACTED]" in raw


def test_main_injects_durable_activity_and_records_completed_turns():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "durable_recent_context(limit=12)" in text
    assert 'journal_activity("user", full_in)' in text
    assert 'journal_activity("assistant", full_out)' in text


def test_task_completion_is_written_to_activity_history():
    text = Path("core/task_continuity.py").read_text(encoding="utf-8")
    assert "_journal('task_completed'" in text

def test_recall_memory_searches_activity_after_restart(tmp_path, monkeypatch):
    import memory.activity_journal as journal
    import memory.memory_manager as mm
    monkeypatch.setattr(journal, "PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(mm, "MEMORY_PATH", tmp_path / "long_term.json")
    journal.append("task_completed", "Makalah energi terbarukan selesai dan dikirim ke HP")
    result = mm.search_memory("makalah", limit=8)
    assert "activity/task_completed" in result
    assert "makalah" in result.lower()
