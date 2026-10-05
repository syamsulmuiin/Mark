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
    assert 'if not save_direct:' in server


def test_direct_receive_is_explicit_only():
    server=text('dashboard/server.py')
    direct=server[server.index('    async def send_server_file('):server.index('    async def _send_attachment_inbox')]
    assert direct.index('if not save_direct:') < direct.index('self.call_device(destination_device, "file.receive"')
    assert 'requested_destination = "Downloads/Mark"' in direct


def test_tool_contract_defaults_to_inbox_and_exposes_explicit_save():
    tools=text('core/live_tools.py')
    assert "By default the file is delivered to the recipient's durable Attachment Inbox" in tools
    assert '"save_direct": {"type":"BOOLEAN"' in tools
    assert '"destination": {"type":"STRING"' in tools
    assert 'Do not infer direct saving' in tools


def test_router_requires_inbox_by_default_and_receive_only_for_direct_save():
    main=text('main.py')
    assert 'required_capability="file.receive" if save_direct else "attachment.inbox"' in main
    assert 'direct saving requires it to be online' in main
    ast.parse(main)
