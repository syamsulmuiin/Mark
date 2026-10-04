from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_server_browser_dependency_has_single_root_source():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "playwright>=1.40,<2" in requirements
    assert not (ROOT / "requirements-browser.txt").exists()


def test_desktop_companion_keeps_its_own_runtime_dependencies():
    requirements = (ROOT / "desktop-companion" / "requirements.txt").read_text(encoding="utf-8")
    assert "playwright>=1.40,<2" in requirements
    assert "PyQt6" in requirements
    assert "sounddevice" in requirements


def test_server_requirements_do_not_gain_desktop_ui_dependencies():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    for forbidden in ("pyqt6", "sounddevice", "pyautogui", "mss>=", "opencv-python"):
        assert forbidden not in requirements


def test_setup_installs_only_root_server_requirements():
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert '"requirements.txt"' in setup
    assert "requirements-browser.txt" not in setup
    assert '"playwright", "install", "chromium"' in setup
