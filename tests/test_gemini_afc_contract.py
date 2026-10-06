from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_rest_calls_route_through_chat_in_both_runtimes():
    for rel in ("core/gemini.py", "desktop-companion/runtime/core/gemini.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "cl.chats.create(model=model, config=config)" in text, rel
        assert "chat.send_message(contents)" in text, rel
        assert ".models.generate_content(" not in text, rel
        assert ".models.generate_content_stream(" not in text, rel


def test_no_direct_models_generation_anywhere_in_runtime_tree():
    roots = [ROOT / "core", ROOT / "actions", ROOT / "plugins", ROOT / "desktop-companion" / "runtime"]
    offenders = []
    for base in roots:
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if ".models.generate_content(" in text or ".models.generate_content_stream(" in text:
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
