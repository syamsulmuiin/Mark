"""Fixed-provider inference for explicitly authorized capability profiles."""

from __future__ import annotations

import json
from urllib.request import Request
from urllib.error import HTTPError
from core.llm_http import urlopen
from core.llm_trace import traced_text_call


def infer(profile, prompt, *, images=None, timeout=30, settings=None):
    provider, model = profile["provider"], profile["model"]
    key = profile.get("api_key", "")

    def invoke():
        if provider == "gemini":
            parts = [{"text": prompt}] + [
                {"inlineData": {"mimeType": "image/jpeg", "data": i}}
                for i in (images or [])
            ]
            body = {"contents": [{"role": "user", "parts": parts}]}
            request = Request(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + model
                + ":generateContent",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                method="POST",
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
            except HTTPError as exc:
                raise RuntimeError(f"gemini HTTP {exc.code}") from None
            if len(raw) > 4 * 1024 * 1024:
                raise RuntimeError("Gemini profile response too large")
            try:
                candidate = json.loads(raw)["candidates"][0]
                if candidate.get("finishReason") != "STOP":
                    raise ValueError()
                result = "\n".join(
                    p["text"] for p in candidate["content"]["parts"] if "text" in p
                )
                if not result.strip():
                    raise ValueError()
                return result
            except (ValueError, KeyError, IndexError, TypeError):
                raise RuntimeError("Gemini profile response incomplete") from None
        options = {"timeout": timeout}
        if images is not None:
            options["images"] = images
        if provider == "openai_codex":
            from core.llm_codex import generate_text

            return generate_text(model, prompt, **options)
        if provider == "google_oauth":
            from core.llm_google_oauth import generate_text

            return generate_text(model, prompt, **options)
        if provider == "anthropic":
            from core.llm_anthropic import generate_text

            return generate_text(model, prompt, api_key=key, **options)
        from core.llm_compatible import generate_text

        return generate_text(provider, model, prompt, api_key=key, **options)

    return traced_text_call(provider, model, invoke)
