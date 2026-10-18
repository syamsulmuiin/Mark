"""Approval replies must be scoped to the original authenticated socket."""
import asyncio
from dashboard.server import DashboardServer


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


def make_server():
    server = object.__new__(DashboardServer)
    server._device_sockets = {}
    server._active_voice_device = None
    server._approval_pending = {}
    server._approval_completion_targets = {}
    server._approval_result_callback = None
    return server


def test_reply_requires_matching_device_socket_and_request():
    server = make_server()
    android, desktop = Socket(), Socket()
    server._device_sockets = {"android": android, "desktop": desktop}
    server._active_voice_device = "android"
    results = []
    server.set_approval_result_callback(lambda *args: results.append(args))
    assert asyncio.run(server.send_active_approval("request-1", "Delete", "A file")) == "android"
    response = {"request_id": "request-1", "accepted": True}
    assert not server.accept_approval_reply("desktop", desktop, response)
    assert not server.accept_approval_reply("android", desktop, response)
    assert not server.accept_approval_reply("android", android, {"request_id": "other", "accepted": True})
    assert not server.accept_approval_reply("android", android, {"request_id": "request-1", "accepted": "true"})
    assert results == []
    assert server.accept_approval_reply("android", android, response)
    assert results == [("request-1", True)]
    assert not server.accept_approval_reply("android", android, response)


def test_expired_and_reconnected_replies_rejected():
    server = make_server()
    old, new = Socket(), Socket()
    server._device_sockets = {"android": old}
    server._active_voice_device = "android"
    asyncio.run(server.send_active_approval("request-2", "Confirm", "Details"))
    server._device_sockets["android"] = new
    response = {"request_id": "request-2", "accepted": True}
    assert not server.accept_approval_reply("android", old, response)
    assert not server.accept_approval_reply("android", new, response)
    server._device_sockets["android"] = old
    server._approval_pending["request-2"]["expires"] = 0
    assert not server.accept_approval_reply("android", old, response)


def test_completion_is_delivered_only_to_original_socket():
    server = make_server()
    original, replacement = Socket(), Socket()
    server._device_sockets = {"android": original}
    server._active_voice_device = "android"
    asyncio.run(server.send_active_approval("request-3", "Test", "Safe"))
    assert server.accept_approval_reply("android", original,
                                        {"request_id": "request-3", "accepted": True})
    assert asyncio.run(server.send_approval_completion("request-3", True))
    assert original.messages[-1] == {
        "type": "approval.completed", "request_id": "request-3", "status": "succeeded"
    }
    assert not asyncio.run(server.send_approval_completion("request-3", True))

    asyncio.run(server.send_active_approval("request-4", "Test", "Safe"))
    assert server.accept_approval_reply("android", original,
                                        {"request_id": "request-4", "accepted": True})
    server._device_sockets["android"] = replacement
    assert not asyncio.run(server.send_approval_completion("request-4", True))
    assert replacement.messages == []


def test_unverified_completion_is_not_reported_as_failed_or_success():
    server = make_server()
    socket = Socket()
    server._device_sockets = {'android': socket}
    server._active_voice_device = 'android'
    asyncio.run(server.send_active_approval('request-unverified', 'Test', 'Safe'))
    assert server.accept_approval_reply('android', socket, {'request_id': 'request-unverified', 'accepted': True})
    assert asyncio.run(server.send_approval_completion('request-unverified', False, outcome='unverified'))
    assert socket.messages[-1]['status'] == 'unverified'
