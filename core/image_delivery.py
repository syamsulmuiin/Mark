"""Hand verified image artifacts to the captured requesting companion Inbox."""
import json


async def deliver_image_results(result, dashboard, origin_device):
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        return result
    if not isinstance(payload, dict) or 'image_artifacts' not in payload:
        return result
    deliveries = []
    for artifact in payload['image_artifacts']:
        try:
            if dashboard is None or not origin_device:
                raise RuntimeError('Requesting companion unavailable')
            peer = dashboard._mesh.get(origin_device) or {}
            if peer.get('revoked') or 'attachment.inbox' not in peer.get('capabilities', []):
                raise RuntimeError('Inbox capability unavailable')
            if artifact.get('image_verified') is not True:
                raise ValueError('Image was not verified')
            delivery = await dashboard.send_server_file(origin_device, artifact['file_path'])
            if not delivery.get('ok') or not delivery.get('attachment_id'):
                raise RuntimeError('Inbox handoff did not verify')
            deliveries.append(delivery)
        except Exception as exc:
            deliveries.append({'ok':False,'error_type':type(exc).__name__})
    count = sum(d.get('ok') is True for d in deliveries)
    all_delivered = bool(deliveries) and count == len(deliveries) and not payload.get("partial", False)
    payload.update(deliveries=deliveries, delivered_count=count,
                   status='VERIFIED' if all_delivered and not payload.get('download_failures') else
                          'WAITING' if payload['image_artifacts'] else 'FAILED',
                   verified=all_delivered and not payload.get('download_failures'),
                   instruction='Report actual image Inbox handoffs and partial failures. Handoff does not prove device opening or content relevance. Keep downloaded files for delivery retry; do not regenerate a TXT link list or resend successful attachments.')
    return json.dumps(payload, ensure_ascii=False)
