"""Severity-filtered rotating error logging for the headless server."""
from __future__ import annotations

import io
import os
import sys
import threading
from pathlib import Path

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUPS = 5

_WARNING_MARKERS = (
    "warning", "warn:", "[warn", "⚠", "failed", "failure", "error",
    "exception", "traceback", "critical", "fatal", "unavailable",
    "out of quota", "denied", "rejected",
)


class RotatingTextStream(io.TextIOBase):
    """Bounded rotating text sink used by the severity filters."""

    def __init__(self, path: Path, max_bytes: int = DEFAULT_MAX_BYTES, backups: int = DEFAULT_BACKUPS):
        self.path = Path(path)
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self.backups = max(1, int(backups))
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8", errors="replace", buffering=1)

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True

    def isatty(self):
        return False

    def fileno(self):
        return self._file.fileno()

    def _rollover_if_needed(self, incoming: str):
        try:
            current = self.path.stat().st_size
        except OSError:
            current = 0
        if current + len(incoming.encode("utf-8", errors="replace")) <= self.max_bytes:
            return
        self._file.flush()
        self._file.close()
        oldest = self.path.with_name(f"{self.path.name}.{self.backups}")
        oldest.unlink(missing_ok=True)
        for idx in range(self.backups - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{idx}")
            target = self.path.with_name(f"{self.path.name}.{idx + 1}")
            if source.exists():
                os.replace(source, target)
        if self.path.exists():
            os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))
        self._file = self.path.open("a", encoding="utf-8", errors="replace", buffering=1)

    def write(self, text):
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        with self._lock:
            self._rollover_if_needed(text)
            self._file.write(text)
            self._file.flush()
        return len(text)

    def flush(self):
        with self._lock:
            self._file.flush()


class SeverityFilteredStream(io.TextIOBase):
    """Persist only warning/error-like stdout lines to the error sink."""

    def __init__(self, sink: RotatingTextStream):
        self.sink = sink
        self._pending = ""
        self._lock = threading.RLock()

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True

    def isatty(self):
        return False

    @staticmethod
    def _should_persist(line: str) -> bool:
        stripped = line.strip()
        lowered = stripped.casefold()
        if not stripped or stripped.startswith(("You:", "JARVIS:", "SYS:")):
            return False
        if (lowered.startswith("[plugins] plugin discovery complete:") and "0 rejected" in lowered
                or lowered.startswith("[attachment] batch complete") and "failed=0" in lowered):
            return False
        explicit = ("[error", "[warn", "warning:", "error:", "exception:", "traceback",
                    "critical:", "fatal:", "permissionerror:", "runtimeerror:",
                    "modulenotfounderror:", "importerror:")
        if any(token in lowered for token in explicit):
            return True
        return stripped.startswith("[") and any(token in lowered for token in ("❌", "⚠", " failed", " rejected", " unavailable"))

    def write(self, text):
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        with self._lock:
            self._pending += text
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                if self._should_persist(line):
                    self.sink.write(line + "\n")
        return len(text)

    def flush(self):
        with self._lock:
            if self._pending and self._should_persist(self._pending):
                self.sink.write(self._pending)
            self._pending = ""
            self.sink.flush()


def configure_runtime_log(path: Path, max_bytes: int | None = None, backups: int | None = None):
    """Keep error.log limited to warnings/errors while preserving tracebacks.

    Normal stdout is intentionally not persisted by the detached server worker.
    Warning/error-like stdout lines are filtered into the rotating error sink.
    Stderr is written directly to the same sink so Python tracebacks and explicit
    stderr diagnostics are retained in full.
    """
    max_bytes = max_bytes or int(os.getenv("MARK_LIV_LOG_MAX_BYTES", DEFAULT_MAX_BYTES))
    backups = backups or int(os.getenv("MARK_LIV_LOG_BACKUPS", DEFAULT_BACKUPS))
    sink = RotatingTextStream(path, max_bytes=max_bytes, backups=backups)
    sys.stdout = SeverityFilteredStream(sink)
    sys.stderr = sink
    return sink
