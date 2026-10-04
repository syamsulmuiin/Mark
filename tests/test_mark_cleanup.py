from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_android_and_server_share_canonical_download_destination():
    android = (ROOT / "android-companion/app/src/main/java/com/jarvis/companion/AttachmentTransfer.kt").read_text(encoding="utf-8")
    dashboard = (ROOT / "dashboard/server.py").read_text(encoding="utf-8")
    tools = (ROOT / "core/live_tools.py").read_text(encoding="utf-8")
    assert 'Downloads/Mark' in android
    assert 'Downloads/Mark' in dashboard
    assert 'Downloads/Mark' in tools
    assert 'Downloads/MARK-LIV' not in android + dashboard + tools


def test_desktop_uses_canonical_state_and_logger_namespace():
    companion = (ROOT / "desktop-companion/companion.py").read_text(encoding="utf-8")
    local_runtime = (ROOT / "desktop-companion/local_runtime.py").read_text(encoding="utf-8")
    assert '.mark-companion' in companion
    assert '.mark-liv-companion' not in companion + local_runtime
    assert 'mark.companion' in companion + local_runtime
    assert 'mark_liv.companion' not in companion + local_runtime


def test_server_health_and_autostart_use_canonical_mark_identity():
    lifecycle = (ROOT / "core/server_lifecycle.py").read_text(encoding="utf-8")
    dashboard = (ROOT / "dashboard/server.py").read_text(encoding="utf-8")
    assert 'data.get("service") == "Mark"' in lifecycle
    assert '"service": "Mark"' in dashboard
    assert 'Mark-Server' in lifecycle
    assert 'com.mark.server.plist' in lifecycle
    assert 'mark.service' in lifecycle
    assert 'MARK-LIV-Server' not in lifecycle
    assert 'com.markliv.server' not in lifecycle
    assert 'mark-liv.service' not in lifecycle


def test_hud_branding_is_current_while_legal_attribution_remains():
    hud = (ROOT / "desktop-companion/hud.py").read_text(encoding="utf-8")
    assert 'Desktop Companion HUD core' in hud
    assert 'Original MARK LV' not in hud
    assert 'https://github.com/FatihMakes/Mark-LV' in hud
    assert 'CC BY-NC 4.0' in hud
