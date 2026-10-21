# Providers and authentication

## Routing

Mark has two configured model roles:

| Role | Use |
| --- | --- |
| Text | Typed replies, reasoning, planning, document/code authoring, and repair diagnosis |
| Live | Voice input/output, live interaction, and calls to the host executor |

Only the selected primary model for each role is used. Errors do not authorize another provider or model. Voice delegation is guided by instructions and tool calls; it is not a deterministic speech-to-text, agent, and text-to-speech pipeline. Typed chat remains text-only.

## Text adapters

| Provider | Authentication and requirements |
| --- | --- |
| Google Gemini | Gemini API key |
| OpenAI API | OpenAI API key |
| OpenAI/Codex account | Native device-code or browser PKCE login; no CLI required |
| Anthropic Claude API | Anthropic API key; Claude.ai subscription login is not implemented |
| DeepSeek | DeepSeek API key |
| Ollama local | Running local Ollama service |
| Ollama cloud | Cloud service credentials |
| OpenRouter | API key or native browser PKCE setup |
| Google OAuth | User-owned Desktop OAuth client and Cloud project with the required API enabled |

Local Ollama requires its model service. API adapters connect directly without a provider CLI. Google OAuth is Developer API access, not Gemini CLI subscription access.

## Live adapters

| Provider | Authentication |
| --- | --- |
| Gemini Live | Gemini API key |
| OpenAI Realtime | OpenAI API key and a separate Realtime model selection |

OpenAI/Codex account login does not provide Realtime API credentials. Gemini Text OAuth does not replace Live API-key authentication. Realtime reconnects create a fresh provider session; local task and conversation continuity remain host responsibilities.

## Setup

Run `python setup.py` and select LLM configuration:

1. Complete Text provider selection, credentials, and model selection.
2. Complete Live provider selection, credentials, and model selection.
3. Restart with `python main.py --restart`.

Saved models remain provider-specific. Cancelling setup preserves the existing configuration. The OpenAI account catalog offers numbered model choices; manual entry remains available when discovery fails. An empty answer retains an existing saved model, not an arbitrary catalog default.

Native OAuth credentials are stored under ignored `config/provider_auth/` with owner-only permissions. Mark does not import other applications' token files. Refresh failures that invalidate authorization require a new login.

Browser PKCE setup prints an authorization URL and accepts the full localhost callback URL through protected input. Callback URI/state are validated. On a headless server the localhost page may fail to load; the returned URL can still be copied. No authentication method is selected as an automatic fallback.

## Troubleshooting and evidence

- Authentication HTTP 530 indicates an upstream/gateway failure, not proof of an incorrect key or model. Use the reported endpoint stage and available edge diagnostics; do not expose tokens or raw authentication responses.
- `llm_routing` records configured routes. `text_provider_request` records the provider/model actually called, with started/succeeded/failed stages.
- `live_connected` identifies the Live model that connected. Model identity in conversation comes from host metadata rather than training identity.
- Provider access, native account protocols, model availability, and real audio behavior need deployment testing. Mocked protocol tests do not establish account access.

### Image search review

Image attachment selection uses an explicit image-input path on the configured primary Text provider, without creating a separate model role or Live session. Adapters encode bounded JPEG previews using the provider's image content format. Gemini/Google OAuth, OpenAI API/Codex account, Claude, OpenRouter and Ollama can submit image inputs, but the selected model must support them. DeepSeek is unsupported by this path. Unsupported providers and rejected/incomplete responses fail closed; no other model is selected automatically. Existing plain-text calls keep their original payload format. Visual matches are model assessments; they do not certify provenance, official status or licensing.
