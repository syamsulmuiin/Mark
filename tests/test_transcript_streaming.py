import ast
from pathlib import Path


def _load_partial_helper():
    source = Path(__file__).parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_partial_transcript_entries")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[node.name]


_partial_transcript_entries = _load_partial_helper()


def test_partial_transcript_preserves_input_and_output_on_rollover():
    assert _partial_transcript_entries(["buat laporan"], ["Saya mulai"], "JARVIS") == [
        ("user", "buat laporan"),
        ("jarvis", "Saya mulai"),
    ]


def test_partial_transcript_ignores_empty_buffers():
    assert _partial_transcript_entries([], [], "JARVIS") == []
