"""Payload-free evidence of the selected text provider actually being called."""
from __future__ import annotations

import uuid
from pathlib import Path

TRACE_LOG = Path(__file__).resolve().parent.parent / "runtime" / "interaction.log"


def traced_text_call(provider, model, run):
    request_id = uuid.uuid4().hex
    def event(stage, **fields):
        from core.interaction_log import write_event
        write_event(TRACE_LOG, 'text_provider_request', provider=provider, model=model,
                    stage=stage, request_id=request_id, **fields)
    event("started")
    try:
        result = run()
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError("Configured Text provider returned no text")
    except Exception as exc:
        event("failed", error_type=type(exc).__name__)
        raise
    event("succeeded")
    return result
