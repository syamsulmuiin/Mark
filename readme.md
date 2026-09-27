# MARK-LIV / JARVIS

MARK-LIV is a headless JARVIS server with native companion clients for Android, Windows, Linux, and macOS. The server owns the AI session, trusted-device mesh, memory, scheduling, remote transport, and server-side services. Interactive voice and device-local UI execution belong to companions.

## Project language policy

Project-facing source comments, documentation, prompts, logs, UI text, and examples are maintained in English. Natural-language compatibility aliases may contain non-English input literals only where required for multilingual command recognition; those aliases belong in `core/language_compat.py`.

## Architecture

```text
                         MARK-LIV SERVER
                            (headless)
                                |
             +------------------+------------------+
             |                  |                  |
          Android          Desktop A          Desktop B
         Companion          Companion           Companion
             |                  |                  |
       local device UI     local device UI    local device UI
       companion voice     companion voice    companion voice
```

The server has no local conversational GUI, microphone, speaker, or interactive CLI. Supported administrative commands are:

```text
--start
--stop
--enable
--disable
--pair
```

`--server-worker` is internal.

A request received from a companion is origin-first. Device-local effects execute on the originating companion unless the user explicitly targets another paired device or the server. `origin_device_id` controls command routing; `active_voice_device` independently controls interactive audio delivery. The server does not play conversational audio.

## Server installation

Requirements: Python 3.11+ and a configured Gemini API key.

```bash
python setup.py
python main.py --start
python main.py --pair
```

`setup.py` installs the headless server requirements and runs first-time configuration. Existing configuration is preserved. On Linux, including Armbian, setup uses a project-local virtual environment when required to avoid modifying an externally managed system Python.

The root server installation intentionally excludes desktop GUI, local audio, camera, screen capture, keyboard/mouse automation, and desktop-window dependencies. Desktop-only dependencies live under `desktop-companion/`.

### Administrative commands

| Command | Purpose |
|---|---|
| `python main.py --start` | Start the detached headless server worker |
| `python main.py --stop` | Stop the tracked server worker |
| `python main.py --enable` | Enable per-user autostart and start the server |
| `python main.py --disable` | Remove autostart without silently stopping a running server |
| `python main.py --pair` | Create a short-lived Pair Code on a running server |

## Pairing and remote access

Pairing supports the configured public endpoint as well as supported local transport. The default deployment configuration is stored in `config/network.json`; environment variables are optional overrides.

A Pair Code is short-lived and does not replace device identity. Paired devices use their device identity and advertised/permitted capabilities after pairing.

Network configuration resolution is:

```text
environment override -> config/network.json -> built-in safety default
```

The standalone desktop runtime carries its corresponding network configuration. Android receives its public URL through build configuration.

## Companion clients

### Android

Source: `android-companion/`.

Android provides companion voice, application launch/close, supported device functions, and user-approved Accessibility UI automation. Accessibility must be enabled by the user in Android Settings. MARK-LIV does not silently require root, ADB/Shizuku, Device Owner, or arbitrary shell access.

### Windows / Linux / macOS

Source: `desktop-companion/`.

```bash
python desktop-companion/install.py
python desktop-companion/companion.py
```

The desktop companion carries its own local runtime so device-side work executes on that companion rather than turning the headless server into a desktop-control endpoint.

## Application-agnostic device automation

Companion UI automation is capability-driven, not application-driven. Application names, package names, contacts, symbols, media titles, document names, websites, and other domain values are target data only. They do not select a special automation policy.

The generic execution model is:

```text
inspect -> choose next generic action -> act -> inspect -> verify
                                      ^                     |
                                      +------ recover ------+
```

Generic companion primitives include application launch/close, UI inspection, click/tap, ordinary text entry, scrolling, supported global navigation, and verification.

The same mechanism applies to applications installed after MARK-LIV was built. A missing predefined application recipe is not a reason to hand normal UI work back to the user. When a requested target is not visible, JARVIS should inspect and use available navigation/search/scroll/text/select operations, then inspect again.

Legacy server actions may still provide backend computation or content retrieval, but they must not become an application-specific substitute for companion UI control.

## Credential boundary

Normal user-authorized UI operations should be completed autonomously when the companion exposes the required capability. The intentional boundary is authentication input.

JARVIS must not type, paste, generate, retrieve, infer, or submit a PIN, password, passcode, unlock code, or other authentication credential. When authentication is required, it stops before credential entry/submission and preserves the current application/session state. After the user completes authentication and asks to continue, JARVIS inspects the current state and resumes the unfinished task.

Ordinary non-credential text entry, search, navigation, selection, and normal send/submit actions are not credential operations.

## Voice

Interactive voice belongs to companions. The server brokers the AI session but does not capture local server microphone audio or play conversational TTS locally.

`call_current_device` addresses the companion that originated the current turn. `call_paired_device` addresses an explicitly selected paired device. Name-to-device resolution should prefer the currently online matching record.

The Android companion validates and recreates its streaming audio player when the platform reports a dead or invalid playback object. Unexpected companion transport loss releases stale playback state and schedules reconnection, so normal voice recovery does not require killing and reopening the application.

## Conversation lifecycle and server lifecycle

Ending a conversation is not server shutdown.

```text
end conversation/session
        -> close the conversational interaction
        -> server remains running
        -> companions remain available

explicit server/service shutdown
        -> shutdown_jarvis
        -> server termination
```

`shutdown_jarvis` is reserved for explicit server/service termination intent. Farewell, stop-talking, or end-session intent must not shut down the MARK-LIV server.

## Scheduling

MARK-LIV does not create unsolicited morning news, time, greeting, or briefing schedules. Scheduled workflows run only when explicitly requested by the user.

User-created recurring workflows are persisted in:

```text
~/.jarvis/scheduled_workflows.json
```

At execution time the saved instruction is run then, allowing time-sensitive information to be obtained fresh. Duplicate daily execution is prevented by persisted run state.

## Read-only self-repair diagnostic

`actions/self_repair_diagnostic.py` provides read-only diagnosis. It can inspect the relevant dependency/root-cause path and report findings, files involved, proposed changes, validation steps, risks, and missing evidence.

Diagnostic mode has no apply capability. It must not edit/delete production source, install dependencies, restart the server, or commit/push changes. A vague error statement alone does not authorize repair; explicit concrete diagnostic intent is required.

Protected architecture invariants include headless server operation, origin-first device routing, separation of command and voice routing, companion-only conversational audio, remote pairing, application-agnostic companion UI automation, credential protection, and no unsolicited scheduled content.

## File handling status

The server currently contains upload/download endpoints and a server upload repository. This is not yet a complete generic cross-device file-transfer protocol. Do not describe MARK-LIV as supporting arbitrary companion-to-companion file sharing until common transfer capabilities are implemented across the companions.

Server file-transfer data uses a single-copy SHA-256 object store under project-local `storage/objects/` with metadata under `storage/metadata/`. Upload/share/download are transfer states, not duplicate physical directories. Cross-companion transfers stream through one-time authenticated URLs into a durable recipient-scoped attachment inbox. The recipient chooses Open, Save As or Share. Temporary server objects are retained while inbox references exist (30-day expiry); permanent server retention is explicit. `storage/` is excluded from Git. Source selection is user-directed and can use the native source picker; Android reads only paths/content URIs it can access. Attachment delivery does not force a destination directory.

## Network configuration

The normal deployment configuration is `config/network.json`. Supported environment overrides include the public hostname, dashboard/transport ports, discovery port, and local host settings.

Playwright/browser binaries are not installed automatically on the headless server. If server-side browser automation is intentionally required, install `requirements-browser.txt` separately on a supported platform.

## Security model

Pairing establishes device identity, not blanket authority. Device calls are restricted to advertised/permitted capabilities. Secrets, credentials, private device identity, signing material, and runtime state must remain outside version control. Android Accessibility requires explicit user consent and fails closed when unavailable.

For Android release signing, see `android-companion/SIGNING.md`.

## Runtime behavior

Expected Live-session rollover and temporary transport/network loss use the reconnect/resumption path rather than being treated as a new user conversation. Unexpected application failures retain diagnostic logging.

`runtime/error.log` is a severity-focused rotating diagnostic file. Normal INFO/debug output, successful tool activity, connection status, and conversation transcript are not persisted there. Warning/error-like diagnostics and Python stderr/tracebacks are retained. Rotation remains bounded by the configured size/backups. Runtime model identifiers are centralized in `core/model_config.py`; network settings are centralized in `core/network_config.py`.

The dashboard/transport layer is optional where its dependencies are unavailable, except that a dashboard port ownership conflict remains fatal because it indicates a duplicate server worker.

## Project map

- `main.py` — headless server orchestration and routing.
- `core/server_lifecycle.py` — server start/stop/enable/disable/pair lifecycle.
- `core/live_tools.py` — Live-session tool declarations.
- `core/model_config.py` — provider model identifiers.
- `core/network_config.py` — server network configuration.
- `core/language_compat.py` — isolated multilingual command aliases.
- `actions/` — server/tool actions, schedules, and read-only diagnostic tools.
- `dashboard/` — HTTP/WebSocket transport, pairing/device endpoints, and server upload endpoints.
- `android-companion/` — Android native companion.
- `desktop-companion/` — Windows/Linux/macOS companion and local runtime.
- `memory/` — memory/config management.
- `plugins/` — plugin extension points.

## Troubleshooting

**Server already running:** stop the tracked worker before intentionally replacing/restarting it.

**Pairing says the server is not running:** start the server first.

**A companion application opens but UI control fails:** confirm the required companion accessibility/control permission is enabled, inspect the current UI/state, and retry through the generic inspect -> act -> verify path.

**A device appears offline while another record with the same name is online:** use the current paired-device list/device identity. Routing should prefer the online matching device.

**Voice input works but response audio does not return:** command routing and voice routing are separate; verify the active voice companion without changing the origin command target.

**Ending a conversation stops the server:** this is incorrect behavior. Conversation lifecycle must remain separate from explicit server shutdown.

## Development rules

Preserve existing behavior unless a change is explicitly requested. Fix root causes with the smallest compatible patch. Device automation must remain application-agnostic. Do not add per-application UI recipes when the generic companion capability model can perform the task.

Documentation describes the current implementation. Version-by-version history belongs in `PATCH_NOTES.md`, not in this README.

### Intentional voice end

Ending a voice conversation is terminal for that voice session. The companion records the intentional end before closing transport, so WebSocket close/failure callbacks do not trigger automatic reconnect. Unexpected transport loss still uses self-recovery. A new user-initiated voice connection clears the ended state and starts a new session.

### Server browser runtime

The server installs the Playwright Python package because `browser_control` is a discoverable server action. Setup installs Chromium on x86_64 Windows/Linux/macOS hosts. ARM and other architectures keep the Python runtime but do not receive a forced browser binary install. Companion-origin UI and vision work remains on the companion.

### Host browser policy

The Playwright Python API is a server dependency because `browser_control` is discoverable at runtime. MARK LIV does not download a separate Playwright-managed Chromium browser. Native navigation and interactive automation use compatible browsers installed on the host. If the requested browser cannot be located, interactive automation reports it as unavailable instead of silently substituting another browser.

On Linux, browser metadata uses the detected machine architecture rather than assuming x86_64.

### Generic persistent task continuity

MARK LIV persists unfinished multi-step work independently from the Gemini Live resumption handle. Tasks store their goal, constraints, completion criteria, verified checkpoints, last tool/action result, blocker state, and origin device. Reconnects, Live rollovers, interrupted responses, and server restarts restore the unfinished task and inject an automatic continuation instruction. Completion requires a verified requested end state; credential/user-authentication boundaries pause rather than discard the task.
### Companion camera vision

Companion camera vision uses the generic `camera.capture` capability and always returns real one-shot image bytes. Android selects the requested front or back camera through Camera2. The shared Windows/Linux/macOS desktop companion captures the configured/default host webcam through OpenCV and reports its actual selection as `default` rather than inventing a front/back identity. Camera applications do not need to be opened. Accessibility/UI inspection is never treated as image data and cannot satisfy a camera or visual-screen request.


### Distribution hygiene
Release packages contain source/runtime assets only. Generated Python caches and bytecode, virtual environments, IDE/test caches, logs, build outputs, and the runtime `storage/` repository are excluded. The server creates required runtime storage directories automatically.


### Re-pair after reinstall
If reinstalling a companion creates a new cryptographic device identity, pairing it again with a fresh Pair Code can replace one unambiguous offline stale record for that same companion name. Normal reconnects keep the existing trust record. If several trusted devices share the same name, MARK-LIV preserves them rather than guessing which one to replace.


### Runtime recovery guards
Vision frames are validated and bound to the active Live session so reconnects do not replay stale image payloads. Rejected companion actions are protected by a generic unchanged-action guard: MARK-LIV must re-inspect/replan or change the action before executing the same rejected device operation again.


### Deferred attachment selection and companion controls (v60.10)
Interactive voice file selection is asynchronous: JARVIS completes its spoken instruction before the source companion opens its native file picker. The selected file then continues through the existing single-copy SHA-256 attachment pipeline. Android exposes dedicated Attachments and Device Control actions; Device Control always delegates enablement to Android Accessibility Settings and never enables the service silently. Attachment transfer failures are logged as diagnostics without file contents or one-time transfer tokens.


### Overflow companion menu and final-turn attachment picker (v60.11)
Android keeps the main voice surface uncluttered: Attachments and Device Control are grouped under the top-right overflow menu. Each destination opens a richer status/action dialog instead of occupying the app bar. Deferred attachment selection no longer uses transient SPEAKING/LISTENING state changes. The runtime emits `assistant.turn.complete` only after the completed Live turn has drained from the companion audio queue; Android and Desktop release a pending native file picker only on that event. Attachment lifecycle diagnostics use warning/error severity markers so detached-server `runtime/error.log` retains picker queued/selected/cancelled, transfer complete, and transfer failure checkpoints without file contents, local source paths, hashes, or transfer tokens.
