"""Canonical paths for server-generated artifacts.

User-visible generated files belong under storage/artifacts so the server can
index, transfer, and clean them consistently instead of leaking files into a
Desktop or beside an input file.
"""
from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACT_ROOT = BASE_DIR / "storage" / "artifacts"
WORKSPACE_ROOT = BASE_DIR / "storage" / "autonomy" / "workspaces"
SCRIPT_SUFFIXES = {".py", ".js", ".ts", ".sh", ".ps1", ".rb", ".php", ".java", ".cpp", ".c", ".rs", ".go"}


def inside_workspace(path):
    try:
        Path(path).resolve().relative_to(WORKSPACE_ROOT.resolve())
        return Path(path).suffix.lower() in SCRIPT_SUFFIXES
    except (ValueError, OSError):
        return False



def artifact_path(name: str, subdir: str = "") -> Path:
    safe = Path(str(name or "artifact")).name
    folder = ARTIFACT_ROOT / Path(subdir).name if subdir else ARTIFACT_ROOT
    folder.mkdir(parents=True, exist_ok=True)
    return folder / safe
