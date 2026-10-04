from pathlib import Path
import sys, types

ROOT=Path(__file__).resolve().parents[1]

def test_server_worker_identity_uses_psutil_before_shell(monkeypatch):
    from core import server_lifecycle
    class P:
        def __init__(self,pid): assert pid==4321
        def cmdline(self): return ["python", str(ROOT/"main.py"), "--server-worker"]
    monkeypatch.setitem(sys.modules,"psutil",types.SimpleNamespace(Process=P))
    assert server_lifecycle._is_markliv_worker(4321) is True

def test_unrelated_pid_is_not_markliv_worker(monkeypatch):
    from core import server_lifecycle
    class P:
        def __init__(self,pid): pass
        def cmdline(self): return ["python", "other.py"]
    monkeypatch.setitem(sys.modules,"psutil",types.SimpleNamespace(Process=P))
    monkeypatch.setattr(server_lifecycle.sys,"platform","not-a-real-platform")
    monkeypatch.setattr(server_lifecycle._subprocess,"run",lambda *a,**k: types.SimpleNamespace(stdout="",returncode=1))
    assert server_lifecycle._is_markliv_worker(9) is False

def test_keepalive_rollover_not_consumed_by_generic_bounded_failure():
    src=(ROOT/"main.py").read_text(encoding="utf-8")
    assert "decision.action is ErrorAction.BOUNDED_FAILURE and not _is_rollover_transport" in src
    assert '"keepalive ping timeout" in _err_lower' in src
    assert 'self._session_log[-40:]' in src

def test_android_transcript_has_colon_and_bold_label():
    src=(ROOT/"android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt").read_text(encoding="utf-8")
    assert 'transcriptTurns.addLast("$who: $text")' in src
    assert "StyleSpan(Typeface.BOLD)" in src
    assert "renderTranscript" in src

def test_desktop_transcript_label_is_bold_only_for_prefix():
    src=(ROOT/"desktop-companion/hud.py").read_text(encoding="utf-8")
    assert 'self._tag in ("you", "ai")' in src
    assert "QFont.Weight.Bold" in src
    assert "self._pos < prefix_end" in src
