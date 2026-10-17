"""Android approval failures must be surfaced rather than silently lost."""
from pathlib import Path


def test_android_approval_delivery_is_waited_on_and_errors_are_visible():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "await asyncio.to_thread(\n                    confirm_gate.request," in source
    assert "delivery.result(timeout=5)" in source
    assert "Android approval delivery failed:" in source
    assert "Android approval unavailable:" in source
    assert "Android approval was not delivered" in source
