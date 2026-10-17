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
    assert 'Default to the attachment inbox' in server


def test_model_delivery_cannot_write_companion_files():
    server=text('dashboard/server.py')
    delivery=server[server.index('    async def send_server_file('):server.index('    async def _send_attachment_inbox')]
    assert delivery.index('if save_direct is True:') < delivery.index('self.call_device(')
    assert '"saved_to_destination":False' in delivery


def test_tool_contract_exposes_only_attachment_delivery():
    tools=text('core/live_tools.py')
    delivery=tools[tools.index('"name": "send_server_file"'):tools.index('"name": "call_current_device"')]
    assert "recipient's durable Attachment Inbox" in delivery
    assert '"save_direct"' in delivery
    assert '"destination"' in delivery
    assert 'ONLY when the current user explicitly requests' in delivery


def test_router_requires_attachment_inbox():
    main=text('main.py')
    assert 'required_capability="file.receive" if save_direct else "attachment.inbox"' in main
    assert 'Do not call raw file.receive' in main
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
