from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ACTIVE_IDENTITY_FILES = [
    ROOT / "readme.md",
    ROOT / "SERVER_CLIENT_ARCHITECTURE.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "setup.py",
    ROOT / "requirements.txt",
    ROOT / "android-companion/README.md",
    ROOT / "android-companion/app/src/main/res/layout/activity_main.xml",
    ROOT / "android-companion/app/src/main/java/com/jarvis/companion/JarvisOrbView.kt",
    ROOT / "desktop-companion/README.md",
    ROOT / "desktop-companion/desktop_ui.py",
]


def test_hermes_is_not_an_active_identity():
    for path in ACTIVE_IDENTITY_FILES:
        assert "hermes" not in path.read_text(encoding="utf-8").casefold(), path


def test_current_project_surfaces_use_mark_not_generation_name():
    for path in ACTIVE_IDENTITY_FILES:
        text = path.read_text(encoding="utf-8")
        identity_text = text
        assert "MARK-LIV" not in identity_text, path
        assert "MARK LIV" not in identity_text, path
        assert "MARK LIII" not in text, path
        assert "MARK LV" not in text, path


def test_identity_roles_remain_distinct():
    android_layout = (ROOT / "android-companion/app/src/main/res/layout/activity_main.xml").read_text(encoding="utf-8")
    android_strings = (ROOT / "android-companion/app/src/main/res/values/strings.xml").read_text(encoding="utf-8")
    desktop = (ROOT / "desktop-companion/desktop_ui.py").read_text(encoding="utf-8")
    assert 'android:text="MARK"' in android_layout
    assert 'android:text="JARVIS"' in android_layout
    assert '<string name="app_name">Companion</string>' in android_strings
    assert "J.A.R.V.I.S" in desktop
    assert "Desktop Companion" in desktop


def test_compatibility_identifiers_are_preserved():
    main_activity = (ROOT / "android-companion/app/src/main/java/com/jarvis/companion/MainActivity.kt").read_text(encoding="utf-8")
    gradle = (ROOT / "android-companion/app/build.gradle.kts").read_text(encoding="utf-8")
    mesh = (ROOT / "core/device_mesh.py").read_text(encoding="utf-8")
    assert '"jarvis.command"' in main_activity
    assert 'applicationId = "com.jarvis.companion"' in gradle
    assert 'namespace = "com.jarvis.companion"' in gradle
    assert 'jarvis.command' in mesh
