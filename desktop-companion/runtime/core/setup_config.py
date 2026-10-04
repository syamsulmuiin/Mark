"""Shared first-run configuration for UI, CLI and background runtimes."""
from __future__ import annotations
import getpass, json, os, platform
from pathlib import Path
from runtime.core.network_config import LOCAL_BASE_URL

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "api_keys.json"

def load_config() -> dict:
    try: return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception: return {}

def configured() -> bool:
    d=load_config(); return bool(str(d.get("gemini_api_key") or "").strip()) and bool(str(d.get("os_system") or "").strip())

def save_config(gemini_api_key: str, os_system: str | None=None) -> dict:
    key=str(gemini_api_key or "").strip()
    if not key: raise ValueError("Gemini API key cannot be empty")
    current=load_config(); current["gemini_api_key"]=key
    current["os_system"]=(os_system or platform.system()).strip() or platform.system()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp=CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    try: os.chmod(CONFIG_FILE, 0o600)
    except Exception: pass
    return current

def interactive_setup(force: bool=False) -> bool:
    if configured() and not force: return True
    print("\nJARVIS FIRST-RUN SETUP")
    print("Gemini API key is stored locally in config/api_keys.json and is git-ignored.")
    try: key=getpass.getpass("Gemini API key: ").strip()
    except (EOFError, KeyboardInterrupt): return False
    if not key:
        print("Setup cancelled: API key was empty."); return False
    save_config(key, platform.system())
    print("\nRemote access lets paired devices reach JARVIS outside your home/LAN.")
    try: remote=input("Enable Cloudflare remote access? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt): remote="n"
    if remote not in ("n","no"):
        try:
            from core.cloudflare_tunnel import install, configure_named_tunnel, DEFAULT_HOSTNAME
            install()
            print(f"Permanent endpoint: https://{DEFAULT_HOSTNAME}")
            print(f"Create a remotely-managed Cloudflare Tunnel and map that hostname to {LOCAL_BASE_URL}.")
            token=getpass.getpass("Cloudflare Tunnel token: ").strip()
            if not token: raise ValueError("Tunnel token was empty")
            configure_named_tunnel(token, DEFAULT_HOSTNAME, True)
            print(f"Cloudflare Named Tunnel enabled at https://{DEFAULT_HOSTNAME}.")
        except Exception as e:
            print(f"Cloudflare setup failed: {e}. LAN pairing remains available.")
    print("Setup complete.")
    return True
