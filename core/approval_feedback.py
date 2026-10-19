"""Sanitized spoken feedback for approval decisions and execution outcomes."""


def speech_instruction(outcome: str) -> str:
    messages = {
        "accepted": "Thank the user professionally for permission. Confirm permission was received and the authorized action is starting. Do not claim it has completed.",
        "rejected": "Acknowledge the user's decision professionally. Permission was rejected and this action was not executed.",
        "expired": "Explain professionally that the approval period expired without permission, so this action was not executed.",
        "succeeded": "Thank the user for permission and confirm professionally that the authorized action completed successfully.",
        "unverified": "Confirm permission was received and execution returned, but its result has not been verified. Do not claim success, retry automatically, or request permission again.",
        "waiting": "Confirm permission was received; the action is still pending or queued. Do not claim completion or request permission again.",
        "failed": "Confirm permission was received, but the authorized action failed or could not be verified. Do not claim success.",
        "nested_confirmation_pending": "Explain that the authorized action has not completed because another approval is required. Do not claim success or repeat the request yourself.",
    }
    if outcome not in messages:
        raise ValueError("Unknown approval outcome")
    return (
        "[HOST APPROVAL STATUS] This status is authoritative. " + messages[outcome] +
        " Speak one short natural sentence in the configured primary response language, "
        "or the user's established language in auto mode. Do not call tools, request "
        "another approval, repeat action arguments or read internal identifiers."
    )


class ApprovalSpeechLedger:
    """Coalesce pending statuses and suppress duplicate speech per approval."""
    def __init__(self):
        self.states = {}

    def offer(self, request_id, outcome):
        state = self.states.get(request_id)
        if state and (outcome == state['latest'] or outcome in state['sent']
                      or outcome == 'accepted'):
            return False
        if state is None:
            state = {'latest': outcome, 'sent': set()}
            self.states[request_id] = state
            if len(self.states) > 256:
                del self.states[next(iter(self.states))]
        state['latest'] = outcome
        return True

    def consume(self, request_id, outcome):
        state = self.states.get(request_id)
        if not state or state['latest'] != outcome or outcome in state['sent']:
            return False
        state['sent'].add(outcome)
        return True
