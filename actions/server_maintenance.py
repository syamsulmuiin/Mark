"""Conversation entry point; mutating operations use the host approval gate."""
import json
from core.server_maintenance import maintain, LocalChangesError


def server_maintenance(parameters, **kwargs):
    try:
        return json.dumps(maintain(str((parameters or {}).get('operation', 'status'))), ensure_ascii=False)
    except LocalChangesError as exc:
        from core.interaction_log import write_event
        from core.server_maintenance import BASE_DIR
        write_event(BASE_DIR / 'runtime' / 'interaction.log', 'server_maintenance_blocked',
                    reason='local_changes', blocking_changes=exc.changes, blocking_change_count=exc.total_count)
        return json.dumps({'ok': False, 'status': 'FAILED', 'verified': False,
                           'error': str(exc), 'blocking_changes': exc.changes, 'blocking_change_count': exc.total_count,
                           'instruction': 'These paths block applying an update. This does not mean GitHub has no update. Do not reset, clean, delete or overwrite local files automatically.'})
    except Exception as exc:
        return json.dumps({'ok': False, 'status': 'FAILED', 'verified': False,
                           'error': str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__})


TOOL = {
    'name': 'server_maintenance',
    'description': 'Mark server maintenance menu: status, check GitHub main updates, update scripts, restart, or update_restart. Check/status are read-only. Other operations require one host approval through propose_text_action. Uses only the official Mark origin, refuses dirty/diverged checkouts. Restart is delayed and returns WAITING, never claim completion before checking status after reconnect. For dependency installation use install_dependencies or install_dependencies_restart with one approval. Installs only repository requirements into the running server Python environment in a detached helper; poll status. No APK update is performed.',
    'parameters': {'type': 'OBJECT', 'properties': {'operation': {'type': 'STRING',
        'enum': ['status', 'check', 'update', 'restart', 'update_restart', 'install_dependencies', 'install_dependencies_restart']}}, 'required': ['operation']},
    'handler': server_maintenance,
}
