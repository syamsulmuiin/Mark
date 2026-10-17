"""Anthropic Messages API adapter for Mark's routed text-only requests."""
from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def generate_text(model: str, prompt: str, *, api_key: str, timeout: float = 30.0) -> str:
    if not model.strip() or not prompt.strip() or not api_key.strip():
        raise ValueError("Anthropic model, prompt and API key are required")
    body = json.dumps({
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Anthropic HTTP {exc.code}") from None
    try:
        blocks = data["content"]
        result = "".join(block["text"] for block in blocks if block.get("type") == "text")
    except (KeyError, TypeError):
        raise RuntimeError("Anthropic returned an invalid Messages response") from None
    if not result:
        raise RuntimeError("Anthropic returned no text")
    return result
