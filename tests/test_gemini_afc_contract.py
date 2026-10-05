from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_server_and_desktop_detect_tools_in_mapping_and_sdk_style_config():
    class SDKConfig:
        def __init__(self, tools):
            self.tools = tools

    for rel, name in (("core/gemini.py", "server_gemini_afc"),
                      ("desktop-companion/runtime/core/gemini.py", "desktop_gemini_afc")):
        module = _load(rel, name)
        assert module._config_has_tools({"tools": [{"google_search": {}}]})
        assert module._config_has_tools(SDKConfig([{"google_search": {}}]))
        assert not module._config_has_tools({})
        assert not module._config_has_tools(SDKConfig([]))
        assert not module._config_has_tools(None)


def test_tool_backed_calls_route_through_chat_in_both_runtimes():
    for rel in ("core/gemini.py", "desktop-companion/runtime/core/gemini.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "_has_tools = _config_has_tools(config)" in text, rel
        assert "cl.chats.create(model=model, config=config)" in text, rel
        assert "chat.send_message(contents)" in text, rel
