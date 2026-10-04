"""Central network endpoints and ports for MARK-LIV.

Environment variables override config/network.json, which overrides built-in defaults.
This keeps transport settings in one source of truth without changing default behavior.
"""
from __future__ import annotations
import json, os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "network.json"

def _file_config():
    try:
        data=json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _text(env, key, default):
    value=os.environ.get(env)
    if value is None: value=_file_config().get(key, default)
    return str(value or default).strip()

def _port(env, key, default):
    raw=os.environ.get(env)
    if raw is None: raw=_file_config().get(key, default)
    try: value=int(raw)
    except (TypeError, ValueError): raise ValueError(f"{env}/{key} must be an integer port")
    if not 1 <= value <= 65535: raise ValueError(f"{env}/{key} must be between 1 and 65535")
    return value

PUBLIC_HOSTNAME = _text("ASSISTANT_PUBLIC_HOSTNAME", "public_hostname", "auth.kasirdigital.web.id").removeprefix("https://").removeprefix("http://").rstrip("/")
DASHBOARD_PORT = _port("ASSISTANT_DASHBOARD_PORT", "dashboard_port", 8000)
LAN_HTTPS_PORT = _port("ASSISTANT_LAN_HTTPS_PORT", "lan_https_port", 8001)
DISCOVERY_PORT = _port("ASSISTANT_DISCOVERY_PORT", "discovery_port", 37991)
LOCAL_HOST = _text("ASSISTANT_LOCAL_HOST", "local_host", "127.0.0.1")
LOCAL_BASE_URL = f"http://{LOCAL_HOST}:{DASHBOARD_PORT}"
PUBLIC_BASE_URL = f"https://{PUBLIC_HOSTNAME}"
