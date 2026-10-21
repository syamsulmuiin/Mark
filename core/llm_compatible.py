"""OpenAI-compatible text adapter for Mark chat and reasoning routing.

This module does not replace Gemini Live or support function/tool calls.
Credentials and model names are explicit; no implicit provider fallback.
"""
from __future__ import annotations

import json
from urllib.request import Request
from core.llm_http import urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit

ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "ollama_local": "http://127.0.0.1:11434/v1/chat/completions",
    "ollama_cloud": "https://ollama.com/v1/chat/completions",
}
REMOTE = frozenset({"openai", "deepseek", "openrouter", "ollama_cloud"})


def generate_text(provider: str, model: str, prompt: str, *,
                  api_key: str = "", endpoint: str = "",
                  timeout: float = 30.0, images: list[str] | None = None) -> str:
    """Generate plain text; never send credentials to an arbitrary host.

    Custom endpoints are allowed only for local Ollama. Optional JPEG previews
    use image_url content blocks; the selected model must support images. No
    tools or streaming are claimed here.
    """
    if provider not in ENDPOINTS:
        raise ValueError("Unsupported OpenAI-compatible provider")
    if not model.strip() or not prompt.strip():
        raise ValueError("Model and prompt are required")
    if provider in REMOTE and not api_key.strip():
        raise ValueError(f"API key required for {provider}")
    if endpoint and provider != "ollama_local":
        raise ValueError("Custom remote endpoints are not supported")
    url = endpoint or ENDPOINTS[provider]
    if provider == "ollama_local":
        try:
            parsed = urlsplit(url)
            local = (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                     and parsed.username is None and parsed.password is None
                     and parsed.port is not None and not parsed.fragment)
        except ValueError:
            local = False
        if not local:
            raise ValueError("Local Ollama endpoint must be loopback")
    content = prompt if not images else [{"type":"text", "text":prompt}] + [
        {"type":"image_url", "image_url":{"url":"data:image/jpeg;base64," + data}} for data in images]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"{provider} HTTP {exc.code}") from None
    try:
        result = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"{provider} returned an invalid chat response") from None
    if not isinstance(result, str):
        raise RuntimeError(f"{provider} returned non-text content")
    return result
