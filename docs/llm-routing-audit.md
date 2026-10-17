# LLM routing audit — 2026-10-17

Scope: repository-wide inventory of provider/configuration entry points, direct
SDK calls, typed commands (CLI/UI/dashboard/Android), voice transport, text
reasoning helpers, model storage, dependencies, and companion runtime copies.
This is a routing audit, not a claim that every feature has been device-tested.

## Findings and fixes

| Finding | Result |
| --- | --- |
| Claude advertised as “adapter not installed” but had no implementation | Added stdlib Claude Messages API adapter; no pip SDK required. |
| OpenAI API text adapter existed, but Codex account authorization and Realtime appeared to be missing packages | Kept unsupported options explicit: not implemented, not installable switches. OpenAI API text remains available. |
| Empty setup answers always reset the provider to Gemini | Reuse saved provider, model and key when setup is repeated. |
| A shared chat model could survive provider changes | Save/restore chat models per provider; preserve Gemini's independent REST and Live ladders. |
| UI/CLI and dashboard typed messages went straight to Live | Route selected non-Gemini text providers directly on the host; no model-controlled delegation or Gemini fallback. Preserve the Gemini Live tool path for Gemini selection. |
| Typed provider failure could otherwise be mistaken for a reason to ask Live | Report failure without sending the request to a different provider; redact exception bodies. |
| Code authoring, developer agent and skill synthesis ignored the selected provider | Route pure text reasoning through the selected provider; preserve Gemini SDK response semantics when Gemini is selected. |
| Repair diagnosis explicitly fell back to a throwaway Live session after REST quota exhaustion | Remove Live fallback; diagnosis follows the text provider. |

## Boundaries that still exist

- Hybrid voice transport is **Gemini Live**. Selecting Claude/OpenAI API changes
  typed chat and routed reasoning, not speech transport. Voice reasoning delegates
  through Live tools and an instruction policy; invocation is not deterministic.
  Replacing this requires a separate STT/text-agent/TTS pipeline or an implemented
  Realtime transport. Do not describe this patch as replacing the voice engine.
- Non-Gemini typed chat is text-only. It does not execute commands. The response
  instruction explicitly forbids claiming actions were executed. Existing voice
  tools and host-approved action proposals retain their existing safeguards.
- Image/audio helpers, Gemini-grounded web search and flight/file multimodal
  processing still call Gemini explicitly. They are not claimed to be portable.
- `desktop-companion/runtime` is a separate desktop helper copy, not the headless
  server's text router. Its local Gemini helpers have not become Claude clients.
- Codex account OAuth and OpenAI Realtime are not implemented. Neither is enabled
  by installing the `openai` Python package. OpenAI API text and Claude API text
  adapters use Python's standard library and require their own API keys/models.

## Validation

Regression tests cover provider persistence/model isolation, Claude HTTP
payload/authentication, OpenAI-compatible provider payloads, host routing without
Live calls on success/failure, helper routing/deadlines and no Live diagnostic
fallback. The complete server suite and Python compilation are run before PR.
Real API requests and Android/voice device behavior need deployment testing;
no user API keys are available in this checkout.

## Configure after deployment

Run `python setup.py`, choose to update LLM configuration, select **OpenAI API
(text only)** or **Anthropic Claude API (text only)**, and enter that provider's
API key and exact model ID. Keep Gemini Live configured for voice. Restart the
server after updating code/configuration. No Android rebuild is required for
this server routing change; the Android approval contrast PR is separate.

Protocol references:
- https://platform.claude.com/docs/en/api/messages/create
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
