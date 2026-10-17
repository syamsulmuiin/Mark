"""OpenAI-compatible text adapter for Mark chat and reasoning routing.

This module does not replace Gemini Live or support function/tool calls.
Credentials and model names are explicit; no implicit provider fallback.
"""
from __future__ import annotations

import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError

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
                  timeout: float = 30.0) -> str:
    """Generate plain text; never send credentials to an arbitrary host.

    Custom endpoints are allowed only for local Ollama. No tools, multimodal
    input, or streaming are claimed here.
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
    if provider == "ollama_local" and not (
        url.startswith("http://127.0.0.1:") or
        url.startswith("http://localhost:")
    ):
        raise ValueError("Local Ollama endpoint must be loopback")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
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
