"""Persist host risk decisions by code hash, policy version and Python runtime."""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from core.skill_crucible import PURE_POLICY_VERSION

POLICY_VERSION = "computation-v1"
ASSESSMENT_ROOT = (
    Path(__file__).resolve().parents[1] / "storage/autonomy/script_assessments"
)


def assessment(source, analyze):
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    identity = {
        "source_sha256": digest,
        "policy_version": POLICY_VERSION,
        "pure_policy_version": PURE_POLICY_VERSION,
        "python_version": list(sys.version_info[:3]),
    }
    path = ASSESSMENT_ROOT / (digest + ".json")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if all(
            record.get(key) == value for key, value in identity.items()
        ) and isinstance(record.get("computation_only"), bool):
            return record
    except (OSError, ValueError, AttributeError):
        pass
    safe = bool(analyze(source))
    record = {
        **identity,
        "computation_only": safe,
        "risk": "LOW" if safe else "REVIEW_REQUIRED",
    }
    ASSESSMENT_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=ASSESSMENT_ROOT, delete=False
    ) as output:
        temp = output.name
        json.dump(record, output)
    try:
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return record
