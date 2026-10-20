"""Read-only observations acquired by the host, never copied from model claims."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

from core.server_export_policy import approve_server_export

READ_ONLY_DEVICE_PROBES = {'app.inspect', 'android.ui.inspect'}


def _field(value, field):
    for part in str(field or '').split('.'):
        if part:
            if not isinstance(value, dict) or part not in value:
                raise ValueError('observation_field_unavailable')
            value = value[part]
    return value


class HostObserver:
    def __init__(self, base_dir, capabilities, device_executor):
        self.base_dir = Path(base_dir)
        self.capabilities = capabilities
        self.device_executor = device_executor

    def __call__(self, step, result, world, goal):
        check = step.get('verify') or {}
        probe = check.get('probe') or {}
        section = check.get('section')
        if not probe or not section:
            return False
        if probe.get('type') == 'server_file':
            path = approve_server_export(probe.get('path', ''), base_dir=self.base_dir).path
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                before = os.fstat(stream.fileno())
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
                after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('artifact_changed_during_readback')
            value = {'exists': True, 'size': after.st_size, 'sha256': digest.hexdigest()}
            if probe.get('sha256') and value['sha256'] != probe['sha256']:
                raise ValueError('artifact_hash_mismatch')
            evidence = {'kind': 'server_file_readback', 'path': str(path), **value}
        elif probe.get('type') == 'companion':
            name = probe.get('capability')
            if name not in READ_ONLY_DEVICE_PROBES:
                raise ValueError('read_only_probe_required')
            target = ((goal.get('active_step') or {}).get('execution_target')
                      or (goal.get('execution_context', {}).get('step_targets', {}).get(step.get('id')))
                      or goal.get('requested_target') or goal.get('origin_device'))
            granted = goal.get('execution_context', {}).get('granted_permissions', [])
            cap = self.capabilities.select(name, requested_target=target, granted_permissions=granted)
            if not target or not cap or cap.device_id != target or cap.source != 'companion':
                raise PermissionError('authorized_probe_device_unavailable')
            reply = self.device_executor(cap, dict(probe.get('args') or {}), goal)
            if (not isinstance(reply, dict) or reply.get('ok') is not True
                    or reply.get('verified') is not True or reply.get('status') != 'SUCCESS'
                    or not reply.get('evidence')):
                raise ValueError('device_readback_unverified')
            value = dict(reply)
            # Desktop inspections serialize process details in the result field.
            if isinstance(value.get('result'), str):
                try:
                    value['result'] = json.loads(value['result'])
                except ValueError:
                    pass
            evidence = {'kind': 'paired_device_readback', 'device_id': target,
                        'capability': name, 'call_id': reply.get('call_id'), 'evidence': reply['evidence']}
        else:
            raise ValueError('unsupported_observation_probe')
        world.update_observed(section, _field(value, probe.get('field')), evidence)
        return True
