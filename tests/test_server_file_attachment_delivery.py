import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def text(path): return (ROOT/path).read_text(encoding='utf-8')

def test_send_server_file_defaults_to_attachment_inbox():
    server=text('dashboard/server.py')
    assert 'save_direct: bool = False' in server
    assert 'source_device="server"' in server
    assert '"type":"attachment.new"' in server
    assert 'temporary=False' in server
    assert 'saving is a recipient UI action' in server


def test_model_delivery_cannot_write_companion_files():
    server=text('dashboard/server.py')
    delivery=server[server.index('    async def send_server_file('):server.index('    async def _send_attachment_inbox')]
    assert 'self.call_device(' not in delivery
    assert '"saved_to_destination":False' in delivery


def test_tool_contract_exposes_only_attachment_delivery():
    tools=text('core/live_tools.py')
    delivery=tools[tools.index('"name": "send_server_file"'):tools.index('"name": "call_current_device"')]
    assert "recipient's durable Attachment Inbox" in delivery
    assert '"save_direct"' not in delivery
    assert '"destination"' not in delivery
    assert 'recipient presses Save As' in delivery


def test_router_requires_attachment_inbox():
    main=text('main.py')
    assert 'required_capability="attachment.inbox"' in main
    assert 'Direct file saving is disabled for model tools' in main
    ast.parse(main)


def test_server_file_export_uses_trusted_root_policy_and_provenance():
    server=text('dashboard/server.py')
    direct=server[server.index('    async def send_server_file('):server.index('    async def _send_attachment_inbox')]
    assert 'approve_server_export(source, base_dir=BASE_DIR)' in direct
    assert 'validate_delivery_name(path, destination_name)' in direct
    assert 'source_path=approved.source_path' in direct
    assert '"source_path":approved.source_path' in direct


def test_tool_contract_explains_trusted_export_roots():
    tools=text('core/live_tools.py')
    assert 'trusted server export roots runtime/ or storage/' in tools
    assert 'rejects traversal/symlink escapes' in tools
    assert 'must preserve the original file extension/type' in tools
