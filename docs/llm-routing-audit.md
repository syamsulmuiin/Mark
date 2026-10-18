# LLM routing and adapters — 2026-10-18

Scope: repository-wide inventory of provider/configuration entry points, direct
SDK calls, typed commands (CLI/UI/dashboard/Android), voice transport, reasoning
helpers, model storage, dependencies, and companion runtime copies. This is a
routing audit, not a claim that every feature has been device-tested.

## Available adapters

| Selection | Implementation | Authentication |
| --- | --- | --- |
| Gemini text | Google SDK text adapter | Gemini API key |
| OpenAI API text | Chat Completions, stdlib HTTP | OpenAI API key |
| Anthropic Claude API text | Messages API, stdlib HTTP | Anthropic API key |
| OpenAI Codex text | Native account Responses HTTP stream | Mark-owned device-code OAuth |
| Google OAuth text | Gemini Developer API REST | Own Desktop OAuth client and Cloud project |
| DeepSeek / OpenRouter / Ollama text | OpenAI-compatible HTTP | Provider API key; local Ollama needs no key |
| Gemini Live voice | Existing Google SDK session | Gemini API key |
| OpenAI Realtime voice | Async WebSocket bridge | OpenAI API key |

## Findings and fixes

- Repeated setup previously reset empty answers to Gemini. Provider, model and
  key choices now persist; text model selections are saved separately per provider.
- All typed chat calls the configured Text provider, including Gemini/Gemini.
  Typed chat is text-only; voice tools retain their existing execution path.
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

Text option 3 now performs OpenAI device-code authorization in Mark and uses the
account Responses HTTP stream directly. It requires neither Node.js nor Codex CLI,
and never imports another application's credentials. OAuth credentials are stored
under ignored `config/provider_auth/` with owner-only file permissions. Refresh is
serialized; terminal refresh failure requires explicit sign-in again rather than
replaying revoked credentials. Incomplete/error streams never return partial text
as a successful response. No Mark tools are delegated to the account endpoint.

Google OAuth is a separate Text selection using a user-owned Desktop OAuth client
and Google Cloud project. It uses PKCE and validates the returned callback state
and exact redirect URI. It is not Google AI/Gemini CLI subscription access. Google
Live retains API-key authentication. OpenRouter supports a headless PKCE browser
code exchange in setup; its resulting key is saved only when both setup stages
finish. Claude stays on its direct API-key adapter; see Anthropic's published
restrictions on third-party Claude.ai subscription authentication.

All authentication and response protocol tests use simulated provider responses;
real account permissions and external protocol compatibility require deployment
validation. Failures never change the selected Text or Live provider/model.

## Configure and deploy

Update server code and install `requirements.txt` into
its Python environment. The new explicit `websockets` dependency provides Realtime
transport. Run `python setup.py` and choose to configure LLMs:

1. Select a text provider and enter its model ID. API text providers need their
   own key or a supported native OAuth method; Codex signs in through Mark instead.
2. Select Gemini Live or OpenAI Realtime for voice. Realtime asks for an OpenAI
   API key and a separate Realtime model ID.
3. Restart Mark with `python main.py --restart`. Provider selection changes do not require an Android rebuild.

For key rotation, run `python setup.py` and configure the LLMs. Selecting only
OpenAI text/voice does not require a Gemini key at startup. Text helpers follow
only the selected Text model; no provider/model fallback is used.

## Remaining boundaries

- Voice reasoning delegation to the selected text provider remains driven by
  instructions and tool calls, not a deterministic STT/text-agent/TTS pipeline.
- All typed chat is text-only and cannot execute commands; it must not claim
  actions were performed. Voice tools and approved proposals retain their executor.
- File/flight helpers follow Text. Gemini grounding is used only when Text is Gemini;
  other providers use ordinary web search. Unsupported multimodal Text input fails
  explicitly instead of invoking another provider.
- Interruption detection uses the existing Live session; no Flash classifier or
  auxiliary Live session is created. Legacy desktop-local inference is disabled;
  server reasoning must supply explicit device arguments.
- Idle phone input requires 160 ms above RMS 250; playback-time input requires
  320 ms above RMS 1000 before opening an activity. It preserves the onset and filters isolated spikes, but sustained
  echo/background speech still requires physical-device investigation.
- Real account login, API model access, microphone/speaker timing, interruption
  behavior and Android approval need deployment/device testing. No user credentials
  or devices are available in this checkout.

## Validation

368 tests pass locally, including Claude/OpenAI-compatible payloads, provider/model
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

## Final pre-merge audit

Repository-wide undefined-name/redefinition analysis found and fixed a missing
`os` import in the desktop Windows app-launch fallback. The final audit also
blocks HTTP credential redirects and rejects local Ollama URLs disguised with
userinfo, invalid ports or fragments. Buffered-playback interruption now preserves
an already completed turn so it cannot swallow the next answer. CI checks static
names, compiles server and desktop sources, and runs tests on Python 3.11–3.13.

Android microphone capture now owns a fixed AudioRecord, WebSocket, and generation
for each session. A read that completes after stop/reconnect cannot send PCM to
the replacement session. Old WebSocket callbacks/packets cannot update the new
session, and server disconnect cleanup preserves a replacement socket's audio route.
The existing VoiceEchoController is now connected to the recording session;
communication audio mode and voice-communication playback are used. Effects and
recording resources are released on stop/start failure; the previous audio mode
is restored. The manifest declares MODIFY_AUDIO_SETTINGS.
`audio_capture_status` logs report AEC/NS enabled state, while
`live_input_transcription` records provenance and character count without text/audio.
These changes address proven lifecycle/echo-control gaps, not proof that the
specific repeated “¿Qué?” was acoustically generated by them. Hardware testing
is still required; no word blacklist or additional model is used.

Queued device PCM carries internal socket ownership; the relay discards frames from superseded connections and closes the old activity before a valid source socket changes.

Primary response language is now configurable through setup or `python main.py --language ID` (restart Live afterward). The shared policy is added to Text gateway requests, Gemini reasoning helper instructions, and Live config (also forwarded to OpenAI Realtime). Server config outranks explicit language preference memory; observed language history never replaces a preference. `--language auto` restores adaptive replies. See README for deployment and exceptions.

Live recovery recognizes `BidiGenerateContent session not found or expired` as
session expiry, drops the stale resumption handle and reconstructs the same
configured model with local conversation context. Failed connection attempts
increase retry delay rather than inheriting a successful old session's uptime.
Quota/rate-limit messages take precedence over generic WebSocket 1011 handling;
retries wait 60, 120, 240, then 300 seconds without model/provider fallback.
Expected provider failures use structured diagnostics instead of duplicate stack
traces. Credential redaction handles whitespace and Bearer authorization values.
Playback-aware onset filters quiet residuals even when platform AEC reports active;
quiet spoken interruptions may need a clearer/louder utterance. This is an audio
heuristic, not a guaranteed acoustic echo canceller or word blacklist.

Phone PCM now passes a local WebRTC VAD (mode 2) before energy/onset gating.
Packets are reassembled into complete 20 ms PCM16 frames; accepted frames keep
source ownership metadata and their original byte order. Non-speech cannot
start an activity or extend the speech timeout solely through high RMS. Framing
and VAD history reset on source changes, mute and input gaps. This is local signal
classification, not another LLM or a provider fallback. Real background speech
or residual spoken echo can still pass; physical-device verification is required.
Install updated requirements before restart. Startup checks the required detector
before opening services/Live sessions and reports an explicit missing-dependency
error. Input-transcription diagnostics include a casefolded SHA-256 fingerprint
(first 16 hex characters) to correlate repeats without storing transcript text
in interaction.log; matching fingerprints reveal repeats, not the acoustic cause.

Primary response language now also supplies an input-ASR language hint. Common
short codes/display names map to BCP-47 (`ID`/Indonesian → `id-ID`); regional tags
are preserved. Auto mode leaves language detection automatic; unknown language
display names are not sent as invalid BCP-47. Gemini uses
input_audio_transcription.language_codes in the same configured Live session.
OpenAI Realtime receives the corresponding two-letter transcription language
while preserving its selected transcription model/manual audio turns. This is a
hint, not a guaranteed language lock or a new model. Runtime routing diagnostics
include resolved response language and input hints; transcription diagnostics
also include the provider language code when returned. Install requirements
(Google Gen AI SDK >=2.31) before restarting. No Android rebuild is needed.


OpenAI account setup offers explicit authentication methods: `1` device code or `2` browser PKCE. Browser PKCE works by opening the printed URL on your own device and pasting the full localhost redirect URL into the protected setup prompt; it checks the exact callback and state before exchanging the code. No method/provider switch happens automatically. Browser login avoids the initial device-code endpoint, but its token exchange and later inference still need connectivity from the Mark server.

An authentication HTTP 530 is not proof of a wrong API key, model or account. Setup now reports the fixed endpoint host and authentication stage, plus a bounded Cloudflare edge subcode/Ray ID when present; response bodies, codes and tokens are not echoed. For Cloudflare-origin 530 see [Cloudflare troubleshooting](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-530/). Check the provider and the server network/proxy route using the actual subcode; a local code change cannot guarantee repair of an external gateway/origin outage. Existing configuration remains unchanged if setup fails.
