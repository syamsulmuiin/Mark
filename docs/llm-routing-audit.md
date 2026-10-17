# LLM routing and adapters — 2026-10-17

Scope: repository-wide inventory of provider/configuration entry points, direct
SDK calls, typed commands (CLI/UI/dashboard/Android), voice transport, reasoning
helpers, model storage, dependencies, and companion runtime copies. This is a
routing audit, not a claim that every feature has been device-tested.

## Available adapters

| Selection | Implementation | Authentication |
| --- | --- | --- |
| Gemini text | Existing REST helpers | Gemini API key |
| OpenAI API text | Chat Completions, stdlib HTTP | OpenAI API key |
| Anthropic Claude API text | Messages API, stdlib HTTP | Anthropic API key |
| OpenAI Codex text | Official Codex CLI subprocess | Existing CLI ChatGPT login |
| DeepSeek / OpenRouter / Ollama text | OpenAI-compatible HTTP | Provider API key; local Ollama needs no key |
| Gemini Live voice | Existing Google SDK session | Gemini API key |
| OpenAI Realtime voice | Async WebSocket bridge | OpenAI API key |

## Findings and fixes

- Repeated setup previously reset empty answers to Gemini. Provider, model and
  key choices now persist; text model selections are saved separately per provider.
- Typed UI/CLI/dashboard commands previously went straight to Live. Non-Gemini
  typed chat now calls its configured text provider directly, without delegating
  provider selection to a voice model. Gemini text with OpenAI voice also uses
  its selected text provider. Gemini/Gemini retains the existing Live tool path.
- Code authoring, developer agent, skill synthesis and repair diagnosis follow
  the text provider. Repair diagnosis no longer consumes Live quota as fallback.
- Missing Claude implementation has been added. Codex and Realtime selections
  are now wired to adapter implementations rather than missing-package labels.

## OpenAI Realtime transport

`core/llm_openai_realtime.py` implements Mark's session methods: audio input,
client content, receiving audio/transcripts/tool calls, and returning tool results.
Companion PCM16 at 16 kHz is converted to 24 kHz with phase retained across chunks;
output PCM is already 24 kHz, matching the existing playback queue. Mark's own
speech boundaries control commits; turns under 100 ms do not request responses.
Session startup waits for API configuration acknowledgement. Interruptions cancel
active responses and conservatively remove cancelled audio from provider context.
Image messages are translated to Realtime image content.

Function calls are returned to the **existing Mark executor**, so Android approval,
proposal handoff and other tool safeguards still apply. Undeclared tools, malformed
arguments and unmatched result IDs fail closed. Multiple function results are
returned before creating the next response. The bridge never executes a tool.

Realtime uses its own `realtime_model` setting, independent of Gemini Live models.
No Gemini resumption handles or quota fallbacks are fabricated. Reconnects create
a fresh Realtime session; uninterrupted provider-side session resumption is not
implemented. Text/local memory continuity remains handled by Mark.

## Codex account adapter

Install the official CLI on the **Mark server**, as the same OS user that runs Mark:

```sh
npm install -g @openai/codex
codex login --device-auth
codex login status
```

The human completes the CLI's official sign-in flow. Mark never reads, copies or
stores OAuth token files. Login status must identify ChatGPT authentication;
saved API-key auth is rejected for this account-based selection. CLI versions
must support `exec --ignore-user-config --ephemeral --output-last-message`.

Requests use stdin, an empty temporary working directory, a read-only sandbox,
disabled shell and web search, and no inherited server API-key/token environment
variables. User-configured MCP integrations are not loaded. The adapter is for
text reasoning, not an alternative executor for Mark actions. Failures/timeouts
are reported without forwarding CLI stderr or switching providers.

## Configure and deploy

After this PR is merged, update server code and install `requirements.txt` into
its Python environment. The new explicit `websockets` dependency provides Realtime
transport. Run `python setup.py` and choose to configure LLMs:

1. Select a text provider and enter its model ID. API text providers need their
   own key; Codex checks the existing CLI ChatGPT login instead.
2. Select Gemini Live or OpenAI Realtime for voice. Realtime asks for an OpenAI
   API key and a separate Realtime model ID.
3. Restart Mark. Provider selection changes do not require an Android rebuild.

For key rotation, `python main.py --setup` requests fresh keys. Selecting only
OpenAI text/voice does not require a Gemini key at startup. Gemini-specific helper
features still need their own Gemini credentials if called.

## Remaining boundaries

- Voice reasoning delegation to the selected text provider remains driven by
  instructions and tool calls, not a deterministic STT/text-agent/TTS pipeline.
- Non-Gemini typed chat is text-only and cannot execute commands; it is instructed
  not to claim actions were performed. Existing voice tools and approved proposals
  retain their normal execution path.
- Gemini-grounded web search, file/flight multimodal helpers, semantic barge-in
  classification and the separate desktop companion helper runtime still explicitly
  use Gemini. They are not claimed to be portable merely because voice is Realtime.
- Real account login, API model access, microphone/speaker timing, interruption
  behavior and Android approval need deployment/device testing. No user credentials
  or devices are available in this checkout.

## Validation

280 tests pass locally, including Claude/OpenAI-compatible payloads, provider/model
persistence, typed routing on success/failure without a Live call, Codex subprocess
and auth contracts, Realtime manual audio turns/resampling/transcripts, and guarded
tool-call/result mapping. Python compilation and diff checks pass. All 15 shared
Mark tool declarations also serialize through the real Google SDK config models
into the Realtime JSON schema (manual local integration check).

References:
- https://platform.claude.com/docs/en/api/messages/create
- https://developers.openai.com/api/docs/guides/realtime-conversations
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/developer-commands?surface=cli
