# Mark

Mark is a headless AI assistant server with Android and desktop companions. The server coordinates models, memory, tasks, and file delivery. Companions provide voice input/output and execute actions on their own devices.

## Quick start

Use Python 3.11–3.13 for the tested server environment.

```bash
git clone https://github.com/syamsulmuiin/Mark.git
cd Mark
python setup.py
python main.py --start
```

Setup installs server dependencies and configures Text and Live providers separately. On Linux, use the virtual environment created by setup for subsequent commands. Install and pair a companion to start a conversation.

- [Android companion](android-companion/README.md)
- [Desktop companion](desktop-companion/README.md)
- [Installation and pairing](docs/setup.md)

## Model configuration

Text handles typed chat, reasoning, authoring, and repair diagnosis. Live handles voice sessions. Only the configured primary model for each role is used; there is no automatic provider or model fallback.

Text adapters include Gemini, OpenAI API, OpenAI/Codex account login, Anthropic Claude API, DeepSeek, Ollama, OpenRouter, and Google OAuth. Live supports Gemini Live and OpenAI Realtime. Authentication and model availability depend on the selected provider.

See [providers and authentication](docs/llm-providers.md). Typed chat currently returns text and does not execute tools; voice actions use the host executor and its approval rules.

## Server commands

| Command | Purpose |
| --- | --- |
| `python main.py --start` | Start the background server |
| `python main.py --restart` | Replace the server process and check readiness |
| `python main.py --stop` | Stop the server |
| `python main.py --break` | Force-stop the tracked autonomy worker; keep the server running |
| `python main.py --enable` | Enable per-user autostart |
| `python main.py --disable` | Remove autostart |
| `python main.py --pair` | List pending companion pairing requests |
| `python main.py --language EN` | Set the primary response language; restart to apply to Live |

Use short language codes such as `EN` (English), `ID` (Indonesian), or `JA` (Japanese). `auto` follows the conversation. English project documentation and prompts do not force English user-facing responses.

## Working with Mark

- Device actions default to the requesting companion. Another device or the server must be explicitly targeted.
- File delivery defaults to the attachment Inbox. Direct saving requires an explicit request and a destination supported by the companion.
- Specialized DOCX editing and general code/file tools coexist. Format support depends on installed libraries and verified execution.
- Ordinary read-only operations run directly. Dangerous or unrestricted actions use host approval; a model cannot grant itself permission.
- Self-repair separates diagnosis, guarded source changes, validation, and activation. Passing tests does not prove that a reported device symptom is fixed.
- Ending a conversation leaves the server running. Schedules are created only on request.

## Updates and diagnostics

After the maintenance feature is installed, voice requests can check GitHub updates, update scripts, restart the server, or update and restart. Mutating operations require approval. Local source changes are preserved, and dependency changes require installation before automatic restart.

For manual deployment:

```bash
git pull --ff-only
python main.py --restart
```

Use the server environment's interpreter. Install updated requirements when dependency files change. Server-only changes do not require a new companion APK; Android changes do.

See [operations and troubleshooting](docs/operations.md) for update blockers, logs, recovery, and activation checks.

## Documentation

| Guide | Contents |
| --- | --- |
| [Architecture](SERVER_CLIENT_ARCHITECTURE.md) | Components, trust boundaries, and routing |
| [Setup](docs/setup.md) | Installation, network configuration, and pairing |
| [Providers](docs/llm-providers.md) | Text/Live selection, authentication, and model identity |
| [Operations](docs/operations.md) | Lifecycle, updates, diagnostics, and repair |
| [Emergency stop](docs/emergency-stop.md) | Worker isolation, global hotkey, and stopping limits |
| [Files](docs/files.md) | Attachments, deletion, creation, and revisions |
| [Contributing](CONTRIBUTING.md) | Development and documentation standards |

Compatibility identifiers such as `jarvis.command`, `X-Jarvis-Local`, and `com.jarvis.companion` remain unchanged.
