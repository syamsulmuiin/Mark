"""Safe, no-side-effect smoke test for the companion Flash Approval UI."""
from core import confirm


def test_flash_approval(parameters: dict, **_kwargs) -> str:
    """Only a human approval can cause the success log; no system changes."""
    return confirm.request(
        key="flash_approval_smoke_test",
        title="Tes Flash Approval",
        detail="Simulasi aman: hanya mencatat keberhasilan di log Mark. Tidak mengubah sistem.",
        run=lambda: "Flash Approval berhasil diuji; tidak ada perubahan sistem.",
    )


TOOL = {
    "name": "test_flash_approval",
    "description": (
        "Display a safe Flash Approval popup on the active paired Android or desktop "
        "companion to test Izinkan, Tolak, and 15-second timeout. "
        "No file, setting, process, or device action is performed. "
        "Call this when the user asks to test the approval popup."
    ),
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": test_flash_approval,
}
