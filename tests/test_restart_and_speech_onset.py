from core.speech_onset import SpeechOnset
from core import server_lifecycle as lifecycle


def test_isolated_noise_does_not_start_turn():
    gate = SpeechOnset()
    chunk = {'data': b'\0' * 1024}
    for _ in range(10):
        assert gate.feed(chunk, 500) == []
        assert gate.feed(chunk, 30) == []


def test_sustained_speech_keeps_initial_audio():
    gate = SpeechOnset()
    chunks = [{'data': bytes([i]) * 1024} for i in range(5)]
    for chunk in chunks[:-1]:
        assert gate.feed(chunk, 700) == []
    assert gate.feed(chunks[-1], 700) == chunks
    assert gate.frames == []


def test_disconnect_discards_candidate():
    gate = SpeechOnset()
    chunk = {'data': b'\0' * 4096}
    assert gate.feed(chunk, 500) == []
    gate.reset()
    assert gate.feed({'data': b'\0' * 1024}, 500) == []


def test_restart_cli():
    assert lifecycle._runtime_mode(['--restart']) == 'restart'


def test_restart_waits_for_stop(monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle, '_server_pid', lambda: 123)
    monkeypatch.setattr(lifecycle, '_stop_server', lambda: calls.append('stop'))
    monkeypatch.setattr(lifecycle, '_pid_alive', lambda pid: False)
    monkeypatch.setattr(lifecycle, '_spawn_server', lambda: calls.append('start') or 456)
    assert lifecycle._restart_server() == 456
    assert calls == ['stop', 'start']


def test_restart_aborts_when_stop_fails(monkeypatch):
    monkeypatch.setattr(lifecycle, '_server_pid', lambda: 123)
    monkeypatch.setattr(lifecycle, '_stop_server', lambda: None)
    monkeypatch.setattr(lifecycle, '_pid_alive', lambda pid: True)
    monkeypatch.setattr(lifecycle, '_spawn_server', lambda: (_ for _ in ()).throw(AssertionError('duplicate worker')))
    assert lifecycle._restart_server() is None


def test_restart_stopped_server(monkeypatch):
    monkeypatch.setattr(lifecycle, '_server_pid', lambda: None)
    monkeypatch.setattr(lifecycle, '_spawn_server', lambda: 456)
    assert lifecycle._restart_server() == 456


def test_brief_low_energy_vad_positive_does_not_open_live_turn():
    gate = SpeechOnset()
    frame = {'data': b'\0' * 640}
    for _ in range(8):
        assert gate.feed(frame, 345) == []
    assert gate.feed(frame, 0) == []
    assert gate.frames == []


def test_sustained_quiet_speech_preserves_all_initial_frames():
    gate = SpeechOnset()
    frames = [{'data': bytes([i]) * 640} for i in range(16)]
    for frame in frames[:-1]:
        assert gate.feed(frame, 345) == []
    assert gate.feed(frames[-1], 345) == frames
