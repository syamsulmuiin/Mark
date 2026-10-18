"""Shared best-effort event writer that reports storage failures without payloads."""
from __future__ import annotations
import json
import os
import sys
import threading
import time
from pathlib import Path

_LOCK = threading.RLock()
_FAILURES: dict[str, float] = {}
_REPORT_INTERVAL = 60.0


def write_event(path: Path, event: str, **fields) -> bool:
    path = Path(path)
    key = str(path)
    with _LOCK:
        try:
            record = {'ts': round(time.time(), 3), 'pid': os.getpid(), 'event': event, **fields}
            encoded = json.dumps(record, separators=(',', ':')) + '\n'
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as stream:
                stream.write(encoded)
            _FAILURES.pop(key, None)
            return True
        except (OSError, ValueError, TypeError) as exc:
            now = time.monotonic()
            previous = _FAILURES.get(key)
            if previous is None or now - previous >= _REPORT_INTERVAL:
                _FAILURES[key] = now
                # Never print the event fields, exception text or conversation payload.
                try:
                    print(f'[ERROR] Interaction log write failed: path={path}; error_type={type(exc).__name__}; '
                          'check runtime directory permissions and available disk space.', file=sys.stderr, flush=True)
                except (OSError, ValueError):
                    pass
            return False
