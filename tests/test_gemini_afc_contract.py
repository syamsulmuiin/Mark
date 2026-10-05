from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_server_and_desktop_route_tool_backed_calls_through_chat():
    for rel in ("core/gemini.py", "desktop-companion/runtime/core/gemini.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert 'bool(config.get("tools"))' in text, rel
        assert 'cl.chats.create(model=model, config=config)' in text, rel
        assert 'chat.send_message(contents)' in text, rel
