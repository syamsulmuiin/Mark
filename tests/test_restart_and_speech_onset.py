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


def test_linux_zombie_worker_does_not_block_restart(monkeypatch, tmp_path):
    import psutil
    from types import SimpleNamespace
    monkeypatch.setattr(lifecycle.sys, 'platform', 'linux')
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(status=lambda: psutil.STATUS_ZOMBIE))
    # The old OS-only probe would report this zombie as alive.
    monkeypatch.setattr(lifecycle.os, 'kill', lambda *a: None)
    assert lifecycle._pid_alive(123) is False
    from core import autonomy_engine
    monkeypatch.setattr(autonomy_engine, 'emergency_break', lambda *a: {'status': 'idle'})
    pidfile = tmp_path / 'server.pid'
    pidfile.write_text('123')
    monkeypatch.setattr(lifecycle, '_runtime_paths', lambda: (pidfile, tmp_path / 'error.log'))
    monkeypatch.setattr(lifecycle, '_local_server_identity', lambda **kw: None)
    monkeypatch.setattr(lifecycle, '_spawn_server', lambda: 456)
    assert lifecycle._restart_server() == 456
    assert not pidfile.exists()


def test_linux_running_or_uninspectable_process_remains_alive(monkeypatch):
    import psutil
    from types import SimpleNamespace
    monkeypatch.setattr(lifecycle.sys, 'platform', 'linux')
    monkeypatch.setattr(psutil, 'Process', lambda pid: SimpleNamespace(status=lambda: psutil.STATUS_RUNNING))
    assert lifecycle._pid_alive(123) is True
    def denied(pid):
        raise psutil.AccessDenied(pid)
    monkeypatch.setattr(psutil, 'Process', denied)
    monkeypatch.setattr(lifecycle.os, 'kill', lambda *a: None)
    assert lifecycle._pid_alive(123) is True


def test_server_admin_entrypoint_imports_from_another_working_directory(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    main = Path(__file__).resolve().parents[1] / 'main.py'
    result = subprocess.run([sys.executable, str(main), '--help'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert '--start' in result.stdout and '--restart' in result.stdout
