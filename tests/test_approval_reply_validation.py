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


def test_expiry_logs_one_terminal_resolution_and_rejects_late_reply(monkeypatch):
    import dashboard.server as mod
    events = []
    monkeypatch.setattr(mod, '_interaction_event', lambda event, **fields: events.append((event, fields)))
    server = make_server()
    socket = Socket()
    server._device_sockets = {'android': socket}
    server._active_voice_device = 'android'
    asyncio.run(server.send_active_approval('expiry-test', 'Test', 'Details'))
    server._approval_pending['expiry-test']['expires'] = 0
    assert not server.accept_approval_reply('android', socket, {'request_id': 'expiry-test', 'accepted': True})
    server.discard_pending_approval('expiry-test', outcome='expired')
    resolved = [fields for event, fields in events if event == 'approval_resolved']
    assert len(resolved) == 1
    assert resolved[0]['outcome'] == 'expired'
    assert resolved[0]['approval_id'] != 'expiry-test'
    assert not server._approval_completion_targets


def test_host_timeout_logs_without_device_reply(monkeypatch):
    import dashboard.server as mod
    events = []
    monkeypatch.setattr(mod, '_interaction_event', lambda event, **fields: events.append((event, fields)))
    server = make_server()
    socket = Socket()
    server._device_sockets = {'android': socket}
    server._active_voice_device = 'android'
    asyncio.run(server.send_active_approval('host-timeout', 'Test', 'Details'))
    server.discard_pending_approval('host-timeout', outcome='expired')
    server.discard_pending_approval('host-timeout', outcome='expired')
    assert len([e for e, _ in events if e == 'approval_resolved']) == 1


def test_expiry_notifies_original_socket_once_without_execution():
    server = make_server()
    socket = Socket()
    server._device_sockets = {'android': socket}
    server._active_voice_device = 'android'
    callbacks = []
    server.set_approval_result_callback(lambda *args: callbacks.append(args))
    asyncio.run(server.send_active_approval('silent-expiry', 'Restart', ''))
    assert asyncio.run(server.expire_pending_approval('silent-expiry'))
    assert socket.messages[-1] == {'type': 'approval.ack', 'request_id': 'silent-expiry', 'status': 'expired'}
    assert not asyncio.run(server.expire_pending_approval('silent-expiry'))
    assert not server.accept_approval_reply('android', socket, {'request_id': 'silent-expiry', 'accepted': True})
    assert callbacks == []


def test_expiry_does_not_notify_replacement_socket():
    server = make_server()
    old, new = Socket(), Socket()
    server._device_sockets = {'android': old}
    server._active_voice_device = 'android'
    asyncio.run(server.send_active_approval('old-expiry', 'Restart', ''))
    server._device_sockets['android'] = new
    assert not asyncio.run(server.expire_pending_approval('old-expiry'))
    assert new.messages == []
    assert 'old-expiry' not in server._approval_pending
