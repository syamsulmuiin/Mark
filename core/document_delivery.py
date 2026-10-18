"""Deliver a newly created document to its captured requesting companion."""
from __future__ import annotations


async def deliver_created_document(artifact, dashboard, origin_device):
    if artifact.get('delivery', {}).get('ok') is True:
        return artifact
    result = dict(artifact)
    try:
        if dashboard is None or not origin_device:
            raise RuntimeError('Requesting companion unavailable')
        peer = dashboard._mesh.get(origin_device) or {}
        if peer.get('revoked') or 'attachment.inbox' not in peer.get('capabilities', []):
            raise RuntimeError('Requesting companion cannot receive attachments')
        delivery = await dashboard.send_server_file(origin_device, artifact['file_path'])
        if not isinstance(delivery, dict) or delivery.get('ok') is not True or not delivery.get('attachment_id'):
            raise RuntimeError('Attachment handoff did not verify')
        result['delivery'] = delivery
        result['instruction'] = ('Document created and handed to the requesting companion attachment inbox. '
                                 'Do not send it again or claim it was saved/opened on the device.')
    except Exception as exc:
        result.update(status='WAITING', verified=False, artifact_verified=True,
                      delivery={'ok':False, 'error_type':type(exc).__name__},
                      instruction='The document was created, but attachment delivery did not verify. Do not regenerate it; retry delivery using the existing file_path after reconnecting the requesting companion.')
    return result
