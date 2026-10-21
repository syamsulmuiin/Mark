"""Owner-private discovery checkpoints; never store conclusions or repair authority."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

MAX_AGE_SECONDS = 86400


class DiagnosticProgress:
    def __init__(self, base: Path, scope: str, files: list[str]):
        self.base = base.resolve()
        self.files = set(files)
        digest = hashlib.sha256(scope.encode())
        # Include actual source bytes: dirty edits invalidate progress too.
        for rel in sorted(files):
            path = base / rel
            if path.is_symlink() or not path.resolve().is_relative_to(self.base):
                raise ValueError("Unsafe diagnostic source")
            digest.update(rel.encode() + b"\0")
            with path.open("rb") as source:
                while chunk := source.read(65536):
                    digest.update(chunk)
            digest.update(b"\0")
        self.key = digest.hexdigest()
        self.directory = base / "storage" / "self_repair" / "diagnostic_progress"
        if self.directory.resolve() != self.base / "storage/self_repair/diagnostic_progress":
            raise ValueError("Unsafe diagnostic progress directory")
        self.path = self.directory / (self.key + ".json")

    def load(self) -> tuple[list[str], bool]:
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 2_000_000:
                return [], False
            record = json.loads(self.path.read_text(encoding="utf-8"))
            age = time.time() - float(record["updated_at"])
            inspected = record["inspected"]
            if (record.get("key") != self.key or not 0 <= age <= MAX_AGE_SECONDS
                    or not isinstance(inspected, list)
                    or any(not isinstance(p, str) or p not in self.files for p in inspected)
                    or type(record.get("closure_complete")) is not bool):
                return [], False
            return list(dict.fromkeys(inspected)), record["closure_complete"]
        except (OSError, ValueError, TypeError, KeyError):
            return [], False

    def save(self, inspected: list[str], complete: bool) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"key": self.key, "updated_at": time.time(),
                  "inspected": inspected, "closure_complete": complete}
        fd, name = tempfile.mkstemp(prefix=".progress-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(record, target)
                target.flush()
                os.fsync(target.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
