"""Conservative result assessment shared by execution and task continuity.

Verification describes the reported step only, never an entire user goal.
"""
import json
import re

FAILED = {'INTERRUPTED', 'FAILED', 'ERROR', 'BLOCKED', 'REJECTED', 'DENIED', 'CANCELLED', 'CANCELED', 'EXPIRED'}
WAITING = {'PENDING', 'QUEUED', 'WAITING', 'RUNNING', 'STARTED', 'ACCEPTED', 'IN_PROGRESS', 'ALREADY_HANDLED'}


def assess(result):
    payload = result
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            pass
    if isinstance(payload, dict):
        status = str(payload.get('status') or '').upper()
        if (payload.get('ok') is False or payload.get('success') is False
                or payload.get('error') or status in FAILED):
            return 'FAILED'
        if payload.get('approval_required') is True or payload.get('approval_sent') is True or status in WAITING:
            return 'WAITING'
        if payload.get('executed') is False or payload.get('verified') is False or status == 'UNVERIFIED':
            return 'UNVERIFIED'
        # Wrappers must not hide an inner failure or pending result.
        inner = assess(payload['result']) if 'result' in payload else None
        if inner in {'FAILED', 'WAITING'}:
            return inner
        if payload.get('verified') is True:
            return 'VERIFIED'
        # A durable inbox record verifies server-side handoff, not device saving.
        if status == 'NOTIFIED' and payload.get('attachment_id'):
            return 'VERIFIED'
        if inner:
            return inner
        return 'UNVERIFIED'
    if not isinstance(payload, str) or not payload.strip():
        return 'UNVERIFIED'
    text = payload.strip().casefold()
    if text.startswith(('[confirmation_pending]', '[confirmation_completed]')):
        return 'WAITING'
    if re.match(r'^(?:error\b|failed\b|file not found\b|unknown (?:tool|\w+ action)\b|unsupported\b|no file path\b)', text):
        return 'FAILED'
    if any(marker in text for marker in ('failed:', 'permission denied', 'not permitted', 'device is offline', 'not installed', 'ffmpeg not found', 'could not process:', 'could not read file:')):
        return 'FAILED'
    return 'UNVERIFIED'


def trace_metadata(result, args=None):
    """Log only bounded state codes, never tool input values or exception text."""
    payload = result
    if isinstance(payload, str):
        try: payload = json.loads(payload)
        except (ValueError, TypeError): payload = {}
    fields = {}
    if isinstance(payload, dict):
        for key in ('status', 'reason', 'error_type', 'skill_id', 'fulfillment_stage'):
            value = payload.get(key)
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_]{1,80}', value):
                fields[key] = value
        for key in ('executed', 'verified', 'process_verified', 'skill_reused'):
            if isinstance(payload.get(key), bool):fields[key] = payload[key]
    if assess(result) == 'UNVERIFIED' and 'reason' not in fields:
        fields['reason'] = 'postcondition_unverified'
    for key in ('operation', 'action', 'kind'):
        value = (args or {}).get(key)
        if isinstance(value, str) and re.fullmatch(r'[a-z_]{1,40}', value):fields[key] = value
    return fields
