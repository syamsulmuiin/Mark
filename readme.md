# Mark / JARVIS

Mark is a headless JARVIS server with native companion clients for Android, Windows, Linux, and macOS. The server owns the AI session, trusted-device mesh, memory, scheduling, remote transport, and server-side services. Interactive voice and device-local UI execution belong to companions.
> Compatibility note: protocol identifiers such as `jarvis.command`, `X-Jarvis-Local`, and the Android package `com.jarvis.companion` remain stable because they identify the JARVIS protocol and installed Android application, not a Mark generation.

## Architecture

```text
                         Mark SERVER
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

Android provides companion voice, application launch/close, supported device functions, and user-approved Accessibility UI automation. Accessibility must be enabled by the user in Android Settings. Mark does not silently require root, ADB/Shizuku, Device Owner, or arbitrary shell access.

### Windows / Linux / macOS

Source: `desktop-companion/`.

```bash
python desktop-companion/install.py
python desktop-companion/companion.py
```

The desktop companion carries its own local runtime so device-side work executes on that companion rather than turning the headless server into a desktop-control endpoint. Its interface uses the standard animated reactor core without holographic-face assets. Both companions show a focused dark/cyan Pair Code screen for a new device. The desktop dashboard opens after the signed server `ready` message. Pairing checks public TLS certificates and keeps the UI responsive; desktop errors are stored in `~/.mark-companion/logs/error.log`. Android uses consistent dark and cyan surfaces for pairing and attachment tabs.

## Application-agnostic device automation

Companion UI automation is capability-driven, not application-driven. Application names, package names, contacts, symbols, media titles, document names, websites, and other domain values are target data only. They do not select a special automation policy.

The generic execution model is:

```text
inspect -> choose next generic action -> act -> inspect -> verify
                                      ^                     |
                                      +------ recover ------+
```

Generic companion primitives include application launch/close, UI inspection, click/tap, ordinary text entry, scrolling, supported global navigation, and verification.

Android browser interaction is device-local: `browser.open` or `browser.search` launches the phone's installed browser, then `android.ui.inspect` -> `android.ui.click`/`android.ui.text`/`android.ui.scroll` -> inspect again controls the visible webpage. Browser cookies and sessions remain on the phone. Server `browser_control` must not replace an Android-originated browser request.

The same mechanism applies to applications installed after Mark was built. A missing predefined application recipe is not a reason to hand normal UI work back to the user. When a requested target is not visible, JARVIS should inspect and use available navigation/search/scroll/text/select operations, then inspect again.

Server actions are restricted to headless/backend work. Device-local application, UI, media, messaging, screen/camera, and desktop file operations are packaged in companions and reached through advertised capabilities; they are not imported into the server action registry.

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

`shutdown_jarvis` is reserved for explicit server/service termination intent. Farewell, stop-talking, or end-session intent must not shut down the Mark server.

## Scheduling

Mark does not create unsolicited morning news, time, greeting, or briefing schedules. Scheduled workflows run only when explicitly requested by the user.

User-created recurring workflows are persisted in:

```text
~/.jarvis/scheduled_workflows.json
```

At execution time the saved instruction is run then, allowing time-sensitive information to be obtained fresh. Duplicate daily execution is prevented by persisted run state.

## Safe self-repair and repair knowledge

`actions/self_repair_diagnostic.py` is the read-only diagnosis stage. It traces the relevant source/dependency path, checks prior repair knowledge as historical evidence, verifies that evidence against current source, and reports root cause, confidence, risk, affected files, proposed changes, and validation requirements. A vague error observation is not repair authorization.

`actions/self_repair_apply.py` is a separate transactional apply stage backed by `core/repair_engine.py`. It requires explicit `APPLY_DIAGNOSTIC_REPAIR` authorization and a high-confidence diagnosis. Repair Guard enforces allowed source areas, protected safety files, path traversal protection, file/change budgets, a three-attempt ceiling, and separate `HIGH_RISK_REPAIR_APPROVED` approval for HIGH-risk changes. Model/user supplied shell commands are never executed by the repair validator. Dependency installation, privilege changes, service restart, commit, push, credentials, deployment workflows, and the repair safety implementation itself are outside autonomous repair authority.

Before a write, the engine records a transaction manifest and complete snapshots of every affected file. The candidate is first validated in a temporary repository copy with fixed import, compile, and full test commands. Only a passing sandbox candidate may be written to the working tree; the same fixed health checks then run again. Any write/test/knowledge failure restores every file in the transaction. Interrupted PREPARED/CANDIDATE transactions are recovered before another repair. Runtime transaction/audit/knowledge data lives under ignored `storage/self_repair/`. Audit records redact credential-like values.

Successful repairs are stored as CONFIRMED/verified knowledge only after validation. Failed candidates are stored separately as EXPERIMENTAL failure knowledge, including the hypothesis, validation failure, and rollback result. Historical knowledge is advisory: diagnosis must verify that the current source still has the same root cause before adapting an old fix.

Protected architecture invariants include headless server operation, server/companion execution boundaries, origin-first device routing, separation of command and voice routing, companion-only conversational audio, remote pairing, credential protection, and no unsolicited scheduled content.

## File handling status

Mark provides cross-device attachment transfer between paired Android and Desktop Companions through the server object store. Source Companions expose `file.upload`; destination Companions expose `file.receive`; the attachment inbox supports offline delivery, verified SHA-256/size downloads, recipient Open/Save/Share actions where the platform supports them, and multi-file picker batches. `transfer_file` is the user-facing transaction path; legacy `file.receive` remains a compatibility capability. The server remains the transport/orchestration point rather than pretending local files are directly shared peer-to-peer.

Server file-transfer data uses a single-copy SHA-256 object store under project-local `storage/objects/` with metadata under `storage/metadata/`. Upload/share/download are transfer states, not duplicate physical directories. Cross-companion transfers stream through one-time authenticated URLs into a durable recipient-scoped attachment inbox. The recipient chooses Open, Save As or Share. Temporary server objects are retained while inbox references exist (30-day expiry); permanent server retention is explicit. `storage/` is excluded from Git. Source selection is user-directed and can use the native source picker; Android reads only paths/content URIs it can access. Attachment delivery does not force a destination directory.

## Network configuration

The normal deployment configuration is `config/network.json`. Supported environment overrides include the public hostname, dashboard/transport ports, discovery port, and local host settings.

Playwright and its isolated Chromium runtime are part of the normal headless server setup on supported architectures. Set `SKIP_BROWSER_INSTALL=1` only when the server should provide `web_search` without host browser automation.

## Security model

Pairing establishes device identity, not blanket authority. Device calls are restricted to advertised/permitted capabilities. Secrets, credentials, private device identity, signing material, and runtime state must remain outside version control. Android Accessibility requires explicit user consent and fails closed when unavailable.

For Android release signing, see `android-companion/SIGNING.md`.

## Runtime behavior

Expected Live-session rollover and temporary transport/network loss use the reconnect/resumption path rather than being treated as a new user conversation. Unknown provider/session failures clear a potentially stale resumption handle, preserve bounded local context, notify the Companion of reconnecting state, and start a clean provider session with bounded backoff. Unexpected application failures retain credential-redacted diagnostics.

`runtime/error.log` is a severity-focused rotating diagnostic file. Normal INFO/debug output, successful tool activity, connection status, and conversation transcript are not persisted there. Warning/error-like diagnostics and Python stderr/tracebacks are retained. Rotation remains bounded by the configured size/backups. Runtime model identifiers are centralized in `core/model_config.py`; network settings are centralized in `core/network_config.py`.

The dashboard/transport layer is optional where its dependencies are unavailable, except that a dashboard port ownership conflict remains fatal because it indicates a duplicate server worker.

## Project map

- `main.py` — headless server orchestration and routing.
- `core/server_lifecycle.py` — server start/stop/enable/disable/pair lifecycle.
- `core/live_tools.py` — Live-session tool declarations.
- `core/model_config.py` — provider model identifiers.
- `core/network_config.py` — server network configuration.
- `core/language_compat.py` — isolated multilingual command aliases.
- `actions/` — headless server actions/services only: network/browser retrieval, server-side processing, schedules, monitoring, and guarded diagnostic/repair tools.
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

### Intentional voice end

Ending a voice conversation is terminal for that voice session. The companion records the intentional end before closing transport, so WebSocket close/failure callbacks do not trigger automatic reconnect. Unexpected transport loss still uses self-recovery. A new user-initiated voice connection clears the ended state and starts a new session.

### Server browser runtime

The server installs the Playwright Python package and, on supported architectures, the isolated Chromium runtime during `python setup.py`. This provides headless browser automation on display-less VPS hosts without requiring a desktop. Companion-origin UI and vision work remains on the companion.

### Host browser policy

The server browser context is isolated from Companion cookies and sessions. Display-less Linux uses headless Chromium; visible desktop hosts prefer the explicitly selected installed browser. If first-time Chromium installation is skipped or fails, `web_search` remains available and `browser_control` reports a bounded browser-runtime error.

### Generic persistent task continuity

Mark persists unfinished multi-step work independently from the Gemini Live resumption handle. Tasks store their goal, constraints, completion criteria, verified checkpoints, last tool/action result, blocker state, and origin device. Reconnects, Live rollovers, interrupted responses, and server restarts restore the unfinished task and inject an automatic continuation instruction. Completion requires a verified requested end state; credential/user-authentication boundaries pause rather than discard the task.
### Companion camera vision

Companion camera vision uses the generic `camera.capture` capability and always returns real one-shot image bytes. Android selects the requested front or back camera through Camera2. The shared Windows/Linux/macOS desktop companion captures the configured/default host webcam through OpenCV and reports its actual selection as `default` rather than inventing a front/back identity. Camera applications do not need to be opened. Accessibility/UI inspection is never treated as image data and cannot satisfy a camera or visual-screen request.


### Distribution hygiene
Release packages contain source/runtime assets only. Generated Python caches and bytecode, virtual environments, IDE/test caches, logs, build outputs, and the runtime `storage/` repository are excluded. The server creates required runtime storage directories automatically.


### Re-pair after reinstall
If reinstalling a companion creates a new cryptographic device identity, pairing it again with a fresh Pair Code can replace one unambiguous offline stale record for that same companion name. Normal reconnects keep the existing trust record. If several trusted devices share the same name, Mark preserves them rather than guessing which one to replace.


### Runtime recovery guards
Vision frames are validated and bound to the active Live session so reconnects do not replay stale image payloads. Rejected companion actions are protected by a generic unchanged-action guard: Mark must re-inspect/replan or change the action before executing the same rejected device operation again.


### Deferred attachment selection and companion controls
Interactive voice file selection is asynchronous: JARVIS completes its spoken instruction before the source companion opens its native file picker. The selected file then continues through the existing single-copy SHA-256 attachment pipeline. Android exposes dedicated Attachments and Device Control actions; Device Control always delegates enablement to Android Accessibility Settings and never enables the service silently. Attachment transfer failures are logged as diagnostics without file contents or one-time transfer tokens.


### Overflow companion menu and final-turn attachment picker
Android keeps the main voice surface uncluttered: Attachments and Device Control are grouped under the top-right overflow menu. Each destination opens a richer status/action dialog instead of occupying the app bar. Deferred attachment selection no longer uses transient SPEAKING/LISTENING state changes. The runtime emits `assistant.turn.complete` only after the completed Live turn has drained from the companion audio queue; Android and Desktop release a pending native file picker only on that event. Attachment lifecycle diagnostics use warning/error severity markers so detached-server `runtime/error.log` retains picker queued/selected/cancelled, transfer complete, and transfer failure checkpoints without file contents, local source paths, hashes, or transfer tokens.


### Single-request attachment transaction and companion-styled menus
A Live user turn owns at most one attachment transaction for a source/destination pair. Once native selection is queued, repeated `transfer_file` calls in the same user turn—including model-generated content URIs—reuse the existing transaction status and cannot open another picker or upload another file. The server records completion/failure/cancellation for that request so a retry receives the real outcome rather than starting over. Android companion submenus now follow the main dark/cyan visual language with circular action icons, clearer status copy, and middle-ellipsized filenames that keep the file extension visible.


### Multi-file attachment batches
A single explicit attachment request may select multiple files in one native picker. Android uses `ACTION_OPEN_DOCUMENT` with multi-selection enabled; Desktop uses its native multi-file picker. The selection is sent as one logical batch transaction, while every selected file remains an independent durable attachment in the recipient inbox and single-copy object store. Batch results report total/completed/failed counts and per-item results. Partial failure does not reopen the picker or retry the whole batch. The one-transaction-per-user-turn guard remains in force.


### Unified companion menu

The Android overflow menu uses one dark panel with a compact close icon in the header. Attachments, Device Control, and recipient file actions share the panel and use back navigation without stacked dialogs or prominent footer buttons.

### Permanent server file transfer

Voice requests such as “send this file to the server” use the current companion as source and an explicit server destination. The server retains verified files in its object store and file listing, returning their stored names after upload. Server uploads appear only in read-only Sent history. Sending to another paired device still uses the recipient inbox.

### Attachment completion and history

After the picker uploads files, Mark resumes the requested assistant task or announces delivery to another companion. Assistant uploads appear only in the sender’s Sent history; recipients retain Open, Save As and Share. Success and cancellation no longer create warning logs.

### Voice attachment picker

A new voice request resets the attachment guard as input transcription begins. Unknown local paths trigger the source companion native multi-select picker through transfer_file.

### Attachment and Live recovery fixes

Android document uploads preserve the displayed filename and extension. Attachment batches retain one request through model retries and expose a transferring state. Temporary Gemini Live 1011 disconnects reconnect without duplicate error tracebacks.

### Attachment picker diagnostics and duplicate-name routing
Attachment picker delivery now has explicit `received` and `opened` acknowledgements, persisted by the server diagnostic logger. Android and Desktop remember whether the current assistant turn has already completed, so a picker request arriving immediately after the completion event is opened once instead of waiting forever for an event that already occurred. SPEAKING/THINKING resets that completion latch for the next response.

Device-name resolution now prefers an exact device ID. When several non-revoked records share the same display name, exactly one currently-online match may be selected; multiple online matches remain ambiguous and are never guessed. Historical trust records are not silently deleted because identical model names can represent different physical devices.

## Runtime diagnostics

The headless server owns a rotating `runtime/error.log` plus bounded `runtime/interaction.log` diagnostics. JARVIS can inspect these server logs through the read-only `runtime_diagnostics` action without arbitrary filesystem access; credential-like values are redacted and reads are size/line bounded. When the user explicitly asks Mark to diagnose and repair a concrete server problem, self-repair may use this runtime evidence, trace the current source, create a guarded repair plan, and automatically apply a verified LOW/MEDIUM-risk plan. HIGH-risk repair still requires separate explicit approval. Every applied repair remains transactional with validation and rollback on failure.


## Capability Evolution and Verified Execution

Mark treats a successful function return and a verified real-world outcome as different things. Native companions keep the legacy `ok` / `result` fields for compatibility and additionally return a structured action envelope with `status`, `verified`, `evidence`, and `reason`. The canonical statuses are `SUCCESS`, `FAILED`, `UNVERIFIED`, `WAITING`, and `BLOCKED`. A command that was dispatched but whose post-condition was not observed is `UNVERIFIED`, not `SUCCESS`.

Paired companions also report a capability manifest and persistent per-capability health telemetry. The manifest cannot grant permission: authorization continues to come exclusively from the paired-device capability allowlist. Health, latency, failure counts, and verification semantics are routing/diagnostic evidence only.

The autonomy layer now resolves missing capabilities in this order:

1. select an existing authorized capability;
2. use a VERIFIED/TRUSTED declarative composite skill when one provides the requested capability;
3. when evolution is explicitly allowed, synthesize only a low-risk **pure** generated skill;
4. reject the goal if none of those paths can be made safe.

Generated skills are deliberately narrow. `core/skill_crucible.py` rejects filesystem, network, process, shell, credential, dynamic-import, and dependency-install authority. Candidate code is statically checked, tested in an isolated Python runner, lifecycle-promoted through `EXPERIMENTAL -> CANDIDATE -> VERIFIED`, hashed, and stored in the dynamic skill registry. It is never imported into the Mark server process. Runtime hash mismatch quarantines the skill. `TRUSTED` promotion still requires explicit human approval.

This does not replace Safe Self-Repair. Repair restores broken known behavior; Capability Evolution creates a new low-risk capability when existing authorized capabilities cannot satisfy a goal. Both remain bounded by Mark's authority and verification model.

### Verified capability execution and evolution hardening

Companion capability results distinguish execution from post-condition verification. `UNVERIFIED` means the command returned but the requested external state has not yet been independently observed; it is not counted as a transport/action failure. Device capability telemetry separately tracks execution success/failure, verification coverage, and latency so routing can prefer healthy executors with stronger observable evidence without inventing task completion.

Android Companion uses its user-enabled Accessibility bridge for generic package/UI-state observations after supported actions. Desktop Companion exposes process-backed `app.inspect` and uses process read-back where possible for application launch/close; actions without a reliable cross-platform post-condition remain `UNVERIFIED`.

Generated capabilities remain pure LOW-risk computation. Repeated runtime failures may quarantine a generated skill. Recovery never edits or reactivates quarantined source in place: Mark synthesizes a fresh candidate, reruns the full Skill Crucible, retires the old skill only after the replacement is VERIFIED, and performs at most one recovery retry for that invocation.
