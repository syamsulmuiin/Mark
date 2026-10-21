"""Android approval failures must be surfaced rather than silently lost."""
from pathlib import Path


def test_android_approval_delivery_is_waited_on_and_errors_are_visible():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "await asyncio.to_thread(\n                    confirm_gate.request," in source
    assert "delivery.result(timeout=5)" in source
    assert "Android approval delivery failed:" in source
    assert "Android approval unavailable:" in source
    assert "Android approval was not delivered" in source


def test_android_application_frames_require_authenticated_socket():
    source = (Path(__file__).resolve().parents[1] / 'android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt').read_text()
    assert 'private fun readySocket(): WebSocket? = ws?.takeIf { it === authenticatedWs }' in source
    assert '"ready"->{ authenticatedWs=w;' in source
    assert 'ws?.send(' not in source
    assert 'val socket = readySocket() ?: return' in source
    assert 'val socket=readySocket()' in source
    assert '"expired"->"Waktu persetujuan habis; tindakan tidak dijalankan"' in source
