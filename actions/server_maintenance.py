"""Conversation entry point; mutating operations use the host approval gate."""
import json
from core.server_maintenance import maintain


def server_maintenance(parameters, **kwargs):
    try:
        return json.dumps(maintain(str((parameters or {}).get('operation', 'status'))), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({'ok': False, 'status': 'FAILED', 'verified': False,
                           'error': str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__})


TOOL = {
    'name': 'server_maintenance',
    'description': 'Mark server maintenance menu: status, check GitHub main updates, update scripts, restart, or update_restart. Check/status are read-only. Other operations require one host approval through propose_text_action. Uses only the official Mark origin, refuses dirty/diverged checkouts. Restart is delayed and returns WAITING, never claim completion before checking status after reconnect. Dependency changes require manual installation; no APK update or package install is performed.',
    'parameters': {'type': 'OBJECT', 'properties': {'operation': {'type': 'STRING',
        'enum': ['status', 'check', 'update', 'restart', 'update_restart']}}, 'required': ['operation']},
    'handler': server_maintenance,
}
