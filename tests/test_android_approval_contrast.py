from pathlib import Path


def test_android_approval_dialog_uses_explicit_light_surface():
    source = (Path(__file__).resolve().parents[1] / "android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt").read_text(encoding="utf-8")
    dialog = source.split("private fun showApproval(", 1)[1].split("private fun scheduleReconnect(", 1)[0]
    assert "val white=android.graphics.Color.WHITE" in dialog
    assert "setBackgroundColor(white)" in dialog
    assert "ColorDrawable(white)" in dialog
    assert "android.widget.ScrollView(this)" in dialog
    assert "setTextColor(navy)" in dialog
