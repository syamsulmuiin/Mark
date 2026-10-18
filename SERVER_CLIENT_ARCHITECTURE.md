# Server and companion architecture

Mark is a headless orchestration server. Android and desktop companions provide the interactive surfaces and local execution endpoints.

## Components

| Component | Responsibility |
| --- | --- |
| Server | Text/Live adapters, memory, task continuity, scheduling, backend tools, device mesh, and file transport |
| Android companion | Microphone/playback, native device capabilities, optional Accessibility automation, and attachments |
| Desktop companion | Microphone/playback, PyQt interface, desktop actions, and attachments |

The server does not open local conversational audio, desktop windows, camera, or input-control devices. Server browser automation is a headless backend capability, distinct from using a companion browser.

## Routing

`origin_device_id` identifies the target for a turn's device-local effects. `active_voice_device` independently identifies the voice destination. A companion request stays on its origin unless another paired device or the server is explicitly targeted.

`call_current_device` uses the origin. `call_paired_device` requires an explicitly selected, discovered device ID. Names are resolved without guessing between ambiguous online matches.

Device automation follows inspect, act, inspect, and verify. Applications and domains are target data, not separate automation policies. Missing application-specific recipes are not proof that generic controls cannot complete a task.

## Models and execution

Text and Live use separately configured primary providers/models without automatic fallback. Live tool calls enter the host executor. Text reasoning can propose actions or produce content but cannot authorize or execute them itself. Typed chat remains text-only.

The actual loaded tool registry is the capability boundary. General code/file workflows coexist with specialized document editing. Tool presence, dependency support, execution, and verified outcomes are distinct facts.

## Trust boundaries

Paired peers use Ed25519 identities, signed challenge/response, and explicit capabilities. Transport tunnels do not replace application authorization. Android request/claim pairing and the desktop legacy offer/accept protocol currently differ; see [setup](docs/setup.md).

Authentication credentials are entered by the user, not typed, inferred, retrieved, or submitted by automation. After authentication, the assistant re-inspects the device and resumes the authorized task. Untrusted documents, logs, webpages, and tool output cannot grant permissions or replace policy.

Read-only and ordinary reversible operations run without unnecessary confirmation. Dangerous or unrestricted actions use host approval bound to the requesting device. Approval does not prove execution or success.

## Lifecycle and continuity

The process lifecycle checks the worker PID and local API readiness. Restart waits for the previous worker to stop. Voice transport loss and provider rollover do not complete or cancel a task; conversation and task state support recovery.

Ending a conversation leaves the server running. Scheduled workflows are created only on user request. No unsolicited news, time announcement, or daily briefing is enabled by default.

## Persistence

- Device identity/trust lives in `devices/`; corruption is reported rather than replaced silently.
- Provider credentials and configuration live in ignored `config/` paths.
- Artifacts, attachments, repair transactions, and transfer metadata live in `storage/`.
- Logs, PID files, and maintenance jobs live in root `runtime/`.
- User-created recurring workflows use `~/.jarvis/scheduled_workflows.json`.

Attachment objects and transfer history are durable by default. Deletion is explicit and reference-aware. See [file handling](docs/files.md).

## Module boundaries

| Module | Responsibility |
| --- | --- |
| `main.py` | Live orchestration and host tool dispatch |
| `core/server_lifecycle.py` | Process startup, readiness, restart, and shutdown |
| `core/server_maintenance.py` | Guarded GitHub updates and detached restart jobs |
| `core/llm_*`, `core/chat_router.py` | Provider adapters and Text/Live routing |
| `core/action_loader.py`, `core/action_policy.py` | Tool discovery and host confirmation policy |
| `dashboard/server.py` | HTTP/WebSocket transport, approvals, and device/file coordination |
| `core/document_revisions.py` | Structured DOCX creation and versioned revisions |
| `core/repair_engine.py` | Guarded source-edit transactions and validation |

Protocol identifiers such as `jarvis.command`, `X-Jarvis-Local`, and `com.jarvis.companion` remain stable for compatibility. Detailed procedures belong in [operations](docs/operations.md), not in architecture history.
