"""Mark-owned provider credentials. Never imports another application's login files."""
import json
import os
from pathlib import Path
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1] / 'config' / 'provider_auth'
LOCK = threading.RLock()
PROVIDERS = {'openai_codex', 'google_oauth'}


def _path(provider):
    if provider not in PROVIDERS:
        raise ValueError('Unsupported credential provider')
    return ROOT / (provider + '.json')


def load(provider):
    with LOCK:
        try:
            data = json.loads(_path(provider).read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raise RuntimeError('Provider credentials could not be loaded; sign in again') from None
        return data if isinstance(data, dict) else {}


def save(provider, data):
    with LOCK:
        path = _path(provider)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.auth-')
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def invalidate(provider):
    with LOCK:
        record = load(provider)
        record['invalid'] = True
        save(provider, record)
