"""Approval requests must never be broadcast to inactive companions."""
import asyncio
from dashboard.server import DashboardServer


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, msg):
        self.messages.append(msg)


def test_approval_targets_active_companion_only():
    server = DashboardServer()
    android, desktop = Socket(), Socket()
    server._device_sockets = {"android": android, "desktop": desktop}
    server._active_voice_device = "android"
    owner = asyncio.run(server.send_active_approval("req-1", "Confirm", "Details"))
    assert owner == "android"
    assert android.messages == [{
        "type": "approval.request", "request_id": "req-1",
        "title": "Confirm", "detail": "Details", "timeout_seconds": 15,
    }]
    assert desktop.messages == []


def test_no_active_companion_means_no_approval():
    server = DashboardServer()
    socket = Socket()
    server._device_sockets = {"android": socket}
    server._active_voice_device = None
    assert asyncio.run(server.send_active_approval("req-1", "Confirm", "Details")) is None
    assert socket.messages == []


def test_disconnected_active_companion_never_falls_back_to_other_device():
    server = DashboardServer()
    desktop = Socket()
    server._device_sockets = {"desktop": desktop}
    server._active_voice_device = "android"
    assert asyncio.run(server.send_active_approval("req-1", "Confirm", "Details")) is None
    assert desktop.messages == []
