"""Exercise delayed socket failure after a replacement has authenticated."""
import asyncio
from dashboard.server import DashboardServer


def server():
    host = object.__new__(DashboardServer)
    host._device_sockets = {}
    host._active_voice_device = "phone"
    host._origin_device_id = "phone"
    return host


def test_stale_disconnect_retains_replacement_and_voice_route():
    host = server()
    old, new = object(), object()
    host._device_sockets["phone"] = new
    assert not host._release_device_socket("phone", old)
    assert host._device_sockets["phone"] is new
    assert host._active_voice_device == "phone"
    assert host._release_device_socket("phone", new)
    assert "phone" not in host._device_sockets
    assert host._active_voice_device is None


def test_delayed_audio_send_failure_cannot_remove_replacement():
    host = server()
    replacement = object()

    class OldSocket:
        async def send_bytes(self, pcm):
            host._device_sockets["phone"] = replacement
            raise ConnectionError("old socket closed after replacement")

    host._device_sockets["phone"] = OldSocket()
    asyncio.run(host.send_device_audio(b"\0\0"))
    assert host._device_sockets["phone"] is replacement
    assert host._active_voice_device == "phone"
