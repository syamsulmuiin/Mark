"""MARK LIV headless server setup.

The server installer is intentionally independent from desktop audio, GUI, screen,
camera, and input-control packages. It supports the common Windows, macOS, and
Linux CPU families used by MARK LIV, including Linux ARM64/aarch64 devices such
as Armbian boards.

On Linux, setup uses a project-local virtual environment when the current Python
is not already inside one. This avoids Debian/Ubuntu/Armbian PEP 668
"externally-managed-environment" failures without modifying the system Python.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import venv
from pathlib import Path

OS = platform.system()
ARCH = platform.machine().lower()
HERE = Path(__file__).resolve().parent
VENV_DIR = HERE / ".venv"
MIN_PY = (3, 11)
MAX_TESTED_PY = (3, 13)

_ARCH_ALIASES = {
    "amd64": "x86_64", "x86_64": "x86_64",
    "arm64": "arm64", "aarch64": "arm64",
    "armv7l": "armv7", "armv7": "armv7",
}


def _run(label: str, args: list[str]) -> None:
    print(f"\n[Setup] {label}")
    subprocess.run(args, check=True, cwd=HERE)


def _normalized_arch() -> str:
    return _ARCH_ALIASES.get(ARCH, ARCH or "unknown")


def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def _venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if OS == "Windows" else "bin/python")


def _check_python() -> None:
    version = sys.version_info[:2]
    if version < MIN_PY:
        raise SystemExit(
            f"MARK LIV requires Python {MIN_PY[0]}.{MIN_PY[1]} or newer; "
            f"detected {version[0]}.{version[1]}."
        )
    if version > MAX_TESTED_PY:
        print(
            f"[Setup] Warning: Python {version[0]}.{version[1]} is newer than "
            f"the latest tested version {MAX_TESTED_PY[0]}.{MAX_TESTED_PY[1]}."
        )


def _ensure_linux_venv() -> None:
    if OS != "Linux" or _in_venv() or os.environ.get("ASSISTANT_SETUP_IN_VENV") == "1":
        return
    python = _venv_python()
    if not python.exists():
        print("[Setup] Creating project-local virtual environment at .venv ...")
        try:
            venv.EnvBuilder(with_pip=True).create(VENV_DIR)
        except Exception as exc:
            raise SystemExit(
                "Unable to create .venv. On Debian/Ubuntu/Armbian install the "
                "matching python3-venv package, then run setup.py again. "
                f"Details: {exc}"
            ) from exc
    env = os.environ.copy()
    env["ASSISTANT_SETUP_IN_VENV"] = "1"
    print(f"[Setup] Continuing inside {python}")
    result = subprocess.run([str(python), str(HERE / "setup.py")], cwd=HERE, env=env)
    raise SystemExit(result.returncode)


def main() -> None:
    print(
        f"[Setup] MARK LIV headless server | OS={OS or 'unknown'} | "
        f"architecture={_normalized_arch()} | "
        f"Python={sys.version_info[0]}.{sys.version_info[1]}"
    )
    _check_python()
    _ensure_linux_venv()

    _run("Upgrading packaging tools", [sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    _run("Installing headless server dependencies", [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

    # browser_control is discoverable on the server, so its Python dependency
    # is installed by requirements.txt. MARK LIV controls browsers installed on
    # the host and does not download a separate Playwright-managed browser.
    print("[Setup] Playwright Python runtime installed; browser automation uses host-installed browsers.")

    from core.setup_config import configured, interactive_setup
    if not configured():
        if not interactive_setup(force=True):
            raise SystemExit("JARVIS configuration was not completed.")
    else:
        print("[Setup] Existing JARVIS configuration found; Gemini key is unchanged.")

    python_cmd = str(_venv_python()) if OS == "Linux" and _venv_python().exists() else sys.executable
    print("\n[Setup] Setup complete.")
    print(f'  Start server:     "{python_cmd}" main.py --start')
    print(f'  Enable autostart: "{python_cmd}" main.py --enable')
    print("  Install a companion separately on the device that provides UI/audio/control.")
    print("  Server browser UI automation requires a compatible browser installed on the host.")


if __name__ == "__main__":
    main()
