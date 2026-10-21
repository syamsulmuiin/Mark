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
            if artifact.get('content_verified') is not True:
                raise ValueError('Image content was not reviewed against the request')
            delivery = await dashboard.send_server_file(origin_device, artifact['file_path'])
            if not delivery.get('ok') or not delivery.get('attachment_id'):
                raise RuntimeError('Inbox handoff did not verify')
            deliveries.append(delivery)
        except Exception as exc:
            deliveries.append({'ok':False,'error_type':type(exc).__name__})
    count = sum(d.get('ok') is True for d in deliveries)
    all_delivered = bool(deliveries) and count == len(deliveries)
    goal_met = all_delivered and not payload.get('partial', False) and count == payload.get('requested_count', count)
    payload.update(deliveries=deliveries, delivered_count=count,
                   status='VERIFIED' if goal_met else 'PARTIAL' if all_delivered else
                          'WAITING' if payload['image_artifacts'] else 'FAILED',
                   verified=goal_met, delivery_verified=all_delivered, goal_verified=goal_met,
                   instruction='Report delivered_count out of requested_count. Delivery verification alone is not goal completion. Only reviewed matches count toward the goal; disclose shortages and visual assessment limits. Handoff does not prove device opening, official status or usage rights. Keep downloaded files for delivery retry; do not regenerate a TXT link list or resend successful attachments.')
    return json.dumps(payload, ensure_ascii=False)
