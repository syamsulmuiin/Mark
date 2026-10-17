"""Claude Messages text adapter; uses stdlib HTTP, no optional SDK install."""
from __future__ import annotations
import json
from urllib.request import Request
from core.llm_http import urlopen
from urllib.error import HTTPError

ENDPOINT = "https://api.anthropic.com/v1/messages"


def generate_text(model: str, prompt: str, *, api_key: str = "", timeout: float = 30.0) -> str:
    if not model.strip() or not prompt.strip():
        raise ValueError("Model and prompt are required")
    if not api_key.strip():
        raise ValueError("API key required for anthropic")
    request = Request(ENDPOINT, data=json.dumps({
        "model": model, "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8"), headers={
        "Content-Type": "application/json", "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"anthropic HTTP {exc.code}") from None
    try:
        blocks = data["content"]
        if not isinstance(blocks, list) or not blocks:
            raise ValueError()
        result = "\n".join(block["text"] for block in blocks if block.get("type") == "text")
        if not result.strip() or data.get("stop_reason") == "max_tokens":
            raise ValueError()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise RuntimeError("anthropic returned an invalid or incomplete text response") from None
    return result
