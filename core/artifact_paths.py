"""Canonical paths for server-generated artifacts.

User-visible generated files belong under storage/artifacts so the server can
index, transfer, and clean them consistently instead of leaking files into a
Desktop or beside an input file.
"""
from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = BASE_DIR / "storage" / "artifacts"


def artifact_path(name: str, subdir: str = "") -> Path:
    safe = Path(str(name or "artifact")).name
    folder = ARTIFACT_ROOT / Path(subdir).name if subdir else ARTIFACT_ROOT
    folder.mkdir(parents=True, exist_ok=True)
    return folder / safe
