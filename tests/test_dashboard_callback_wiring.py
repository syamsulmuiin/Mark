from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "main.py"
MAIN = MAIN_PATH.read_text(encoding="utf-8")

def test_removed_orphan_legacy_connect_callback():
    assert "set_connect_callback(self._on_phone_connected)" not in MAIN
    assert "def _on_phone_connected" not in MAIN

def test_jarvis_self_method_references_resolve():
    tree = ast.parse(MAIN)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "JarvisLive")
    defined = {n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    unresolved = set()
    for node in ast.walk(cls):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
            name = node.attr
            if name.startswith("_on_") and name not in defined:
                unresolved.add(name)
    assert not unresolved, f"Undefined JarvisLive callback(s): {sorted(unresolved)}"
