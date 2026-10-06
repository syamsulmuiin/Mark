from pathlib import Path
import importlib

ROOT = Path(__file__).resolve().parents[1]


def test_live_1011_and_deadline_are_transient_transport():
    from core.runtime_errors import Boundary, ErrorAction, classify_error
    for message in (
        "1011 None. Internal error encountered.",
        "1011 None. Deadline expired before operation could complete.",
    ):
        d = classify_error(Boundary.LIVE_SESSION, RuntimeError(message))
        assert d.action is ErrorAction.TRANSPORT_RECONNECT
        assert d.retryable is True
        assert d.traceback is False


def test_duplicate_response_state_resets_only_on_real_voice_activity():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    activity = src[src.index("def _note_voice_activity_start"):src.index("def _note_voice_activity_end")]
    receive = src[src.index("async def _receive_audio"):src.index("# ── Session memory")]
    assert 'self._last_out_logged = ""' in activity
    assert 'self._recent_response_audio.clear()' in activity
    assert 'response_audio_duplicate_suppressed' in receive
    assert 'self._last_out_logged = ""   # new exchange' not in receive


def test_ddg_transport_circuit_breaker_logs_once(monkeypatch, capsys):
    ws = importlib.import_module("actions.web_search")
    monkeypatch.setattr(ws, "_ddg_blocked_until", 0.0)

    class BrokenDDGS:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def text(self, *args, **kwargs):
            raise RuntimeError("HandshakeFailure")

    monkeypatch.setattr(ws, "_get_ddgs", lambda: BrokenDDGS)
    assert ws._ddg_search("one") == []
    assert ws._ddg_search("two") == []
    out = capsys.readouterr().out
    assert out.count("DDG transport unavailable") == 1
    assert "HandshakeFailure" not in out


def test_gemini_quota_is_normalized_after_breaker(monkeypatch, capsys):
    ws = importlib.import_module("actions.web_search")
    monkeypatch.setattr(ws, "_quota_blocked_until", 0.0)

    class G:
        SEARCH = "search"
        @staticmethod
        def call(*args, **kwargs): return None
        @staticmethod
        def last_call_errors(): return (("m", "429 RESOURCE_EXHAUSTED giant provider payload"),)

    import core
    monkeypatch.setattr(core, "gemini", G, raising=False)
    try:
        ws._gemini_search("x")
    except ws._QuotaCooldown:
        pass
    out = capsys.readouterr().out
    assert "quota exhausted" in out.lower()
    assert "giant provider payload" not in out
