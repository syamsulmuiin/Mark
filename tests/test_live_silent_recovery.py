from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")


def test_live_session_has_open_but_silent_watchdog():
    assert "async def _watch_live_stall(self)" in MAIN
    assert "self._unanswered_voice_turns >= 2" in MAIN
    assert '"live_stall_reconnect"' in MAIN
    assert "tg.create_task(self._watch_live_stall())" in MAIN


def test_watchdog_preserves_context_on_reconnect():
    block = MAIN.split("async def _watch_live_stall(self)", 1)[1].split("async def _send_realtime", 1)[0]
    assert "self._reconnect_keep = True" in block
    assert "self._reconnect_event.set()" in block


def test_new_voice_turn_clears_sticky_interruption():
    block = MAIN.split("def _note_voice_activity_start(self)", 1)[1].split("def _note_voice_activity_end", 1)[0]
    assert "self._interrupted = False" in block


def test_provider_progress_cancels_pending_stall_deadlines():
    block = MAIN.split("def _note_live_progress(self)", 1)[1].split("def _note_voice_activity_start", 1)[0]
    assert "self._pending_voice_turns.clear()" in block
    assert "self._unanswered_voice_turns = 0" in block
    recv = MAIN.split("async def _receive_audio(self)", 1)[1].split("async def _play_audio", 1)[0]
    assert "response.data or response.server_content or response.tool_call" in recv
    assert "self._note_live_progress()" in recv


def test_resumption_housekeeping_is_not_false_progress():
    recv = MAIN.split("async def _receive_audio(self)", 1)[1].split("async def _play_audio", 1)[0]
    progress_pos = recv.index("self._note_live_progress()")
    resumption_pos = recv.index("session_resumption_update")
    assert progress_pos < resumption_pos
    progress_guard = recv[:resumption_pos]
    assert "session_resumption_update" not in progress_guard
