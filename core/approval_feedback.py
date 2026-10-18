"""Sanitized spoken feedback for approval decisions and execution outcomes."""


def speech_instruction(outcome: str) -> str:
    messages = {
        "accepted": "Thank the user professionally for permission. Confirm permission was received and the authorized action is starting. Do not claim it has completed.",
        "rejected": "Acknowledge the user's decision professionally. Permission was rejected and this action was not executed.",
        "expired": "Explain professionally that the approval period expired without permission, so this action was not executed.",
        "succeeded": "Confirm professionally that the authorized action completed successfully.",
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
