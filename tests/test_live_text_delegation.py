"""Live may delegate reasoning to configured Text LLM without provider fallback."""
from pathlib import Path


def test_live_exposes_text_delegation_tool():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert '"name": "delegate_to_text_llm"' in source
    assert '"required": ["prompt"]' in source
    assert 'from core.llm_text import generate as generate_text' in source
    assert 'await asyncio.to_thread(generate_text, prompt)' in source
    assert 'Configured Text LLM failed:' in source
