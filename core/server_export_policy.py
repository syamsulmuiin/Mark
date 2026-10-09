"""Trusted server-file export policy.

User-visible server exports are deliberately limited to runtime/ and storage/.
The policy resolves the real path first so traversal and symlink escapes cannot
turn an approved-looking path into access to project source or credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SENSITIVE_NAMES = {".env", "credentials.json", "api_keys.json", "secrets.json"}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


@dataclass(frozen=True)
class ApprovedServerExport:
    path: Path
    source_path: str


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def approve_server_export(source: str | Path, *, base_dir: Path) -> ApprovedServerExport:
    """Return the canonical approved source or raise PermissionError/FileNotFoundError."""
    base = Path(base_dir).resolve()
    raw = Path(str(source or "")).expanduser()
    if not raw.is_absolute():
        raw = base / raw
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"Server file not found: {raw}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Server file not found: {resolved}")

    approved_roots = ((base / "runtime").resolve(), (base / "storage").resolve())
    matched_root = next((root for root in approved_roots if _inside(resolved, root)), None)
    if matched_root is None:
        raise PermissionError("Server file export is allowed only from runtime/ or storage/.")

    lowered = resolved.name.casefold()
    if lowered in SENSITIVE_NAMES or resolved.suffix.casefold() in SENSITIVE_SUFFIXES:
        raise PermissionError("Sensitive credential/key material cannot be exported by the generic server-file tool.")

    return ApprovedServerExport(path=resolved, source_path=resolved.relative_to(base).as_posix())


def validate_delivery_name(source: Path, destination_name: str) -> str:
    """Allow friendly renaming without changing the apparent file type."""
    requested = str(destination_name or "").strip()
    if not requested:
        return source.name
    src_suffix = source.suffix.casefold()
    dst_suffix = Path(requested).suffix.casefold()
    if src_suffix and dst_suffix != src_suffix:
        raise PermissionError(
            f"Destination filename must preserve source file type {src_suffix!r}; got {dst_suffix or '<none>'!r}."
        )
    return requested
