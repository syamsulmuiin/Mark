"""Session summaries use the configured plain-text provider, not Gemini implicitly."""
from pathlib import Path


def test_session_summary_routes_through_chat_router():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    start = source.index("    async def _save_session_summary(")
    end = source.index("    # ── System monitor", start)
    summary = source[start:end]
    assert "from core.chat_router import generate_chat_text" in summary
    assert "asyncio.to_thread(generate_chat_text, prompt)" in summary
    assert "gemini.text" not in summary
