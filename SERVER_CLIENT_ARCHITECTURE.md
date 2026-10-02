# MARK-LIV server / companion architecture

This document describes the current architecture. Historical GUI/CLI/background runtime modes are obsolete and are not supported server access surfaces.

## Headless server

The server owns Gemini Live orchestration, trusted-device routing, persistence/scheduling, server-side actions, and HTTP/WebSocket transport. It has no local microphone, speaker, conversational CLI, or desktop GUI.

Public administrative interface:

```text
python main.py --start
python main.py --stop
python main.py --enable
python main.py --disable
python main.py --pair
```

`--server-worker` is an internal lifecycle flag.

## Companions

Android and desktop companions are the user-facing control/execution surfaces. Voice input/output is companion-only. Desktop companions carry the established local action runtime; Android exposes Android-native capabilities and optional Accessibility UI automation.

## Origin-first routing

Every companion-originated turn has an origin device identity. Unless the user explicitly names another target, device-local actions execute on that origin companion.

Two states must remain separate:

- `origin_device_id`: execution target for the current turn.
- `active_voice_device`: interactive audio destination.

`call_current_device` uses the turn origin. `call_paired_device` is for another explicitly targeted paired device. Device-name resolution prefers an online matching record and should resolve to the canonical paired UUID.

## Voice lifecycle

The server receives/forwards live-session audio but does not render audio. Interactive audio returns to the active voice companion. Command routing must never clear or repurpose voice state. Gemini session rollover/reconnect should preserve active conversational context rather than treating transport rollover as a completed conversation.

## Device mesh and pairing

Paired devices use Ed25519 identities, signed challenge/response, and explicit capabilities. Pairing is available through the configured remote endpoint (`https://auth.kasirdigital.web.id`) and supported local transport. `--pair` creates a short-lived Pair Code on an already-running server.

Cloudflare transport does not replace application-level device authentication or capability authorization.

## Android UI execution

Android Accessibility is opt-in. UI automation follows `inspect -> act -> verify/recover`. Blind scrolling/clicking is not the default strategy. A failed UI operation is not evidence by itself that Internet connectivity or Accessibility is unavailable.

## Scheduling/background behavior

There is no default morning briefing, news poll, or time announcement. News/time are fetched on demand. The scheduler exists to execute workflows explicitly created by the user. Recurring workflow state is stored under `~/.jarvis/scheduled_workflows.json`.

## Diagnostic self-repair and guarded apply

Diagnostic self-repair is user-initiated and conversational first: a vague error observation does not trigger it. JARVIS obtains a concrete symptom and explicit diagnostic/repair intent, announces the read-only diagnostic, and only then starts inspection. A code-level activation guard rejects accidental generic calls. Diagnosis may traverse the complete relevant dependency path without a fixed total file limit.

Direct repair is a separate guarded action. It requires explicit `APPLY_DIAGNOSTIC_REPAIR` authorization and a high-confidence diagnosis, then accepts exact unique replacements in an allowlist of runtime/companion source and documentation files. It has no arbitrary operation-count limit; a total replacement-size budget limits runaway changes. The diagnostic/apply/self-healing implementation itself is immutable through this path. Credentials, core/plugins, deployment/system files, and arbitrary paths are rejected. Candidate Python/XML is validated before atomic replacement; failed writes trigger rollback. The action never installs, restarts, builds, commits, or pushes. Architecture invariants above remain the repair safety boundary.


### v27 runtime stability
- Headless server does not emit unsolicited CPU/RAM voice alerts; system status remains available on demand.
- Gemini side/diagnostic calls no longer open extra Live sessions that can consume Live quota or destabilize the interactive companion voice session.
- Removed retired pinned `gemini-2.5-flash` / `gemini-2.5-flash-lite` fallback names in favor of maintained rolling aliases.
- WebSocket keepalive/close timeouts are treated as transport rollover: conversation context is preserved and the server reconnects quietly.
- Diagnostic self-repair remains read-only and still requires explicit, concrete user diagnostic intent.

## Runtime module boundaries

`main.py` remains the Live conversation orchestrator. Headless process lifecycle is isolated in `core/server_lifecycle.py`; Live-bound tool schemas are isolated in `core/live_tools.py`; model selection is centralized in `core/model_config.py`; and bounded worker stdout/stderr rotation is handled by `core/runtime_log.py`. This separation is structural only and does not move voice or device execution back onto the server.

### v32 network configuration centralization
Network endpoints and ports now use `core/network_config.py` as the server source of truth. Defaults remain unchanged, but deployments can override them with `ASSISTANT_PUBLIC_HOSTNAME`, `ASSISTANT_DASHBOARD_PORT`, `ASSISTANT_LAN_HTTPS_PORT`, `ASSISTANT_DISCOVERY_PORT`, and `ASSISTANT_LOCAL_HOST`, or `config/network.json`. The standalone desktop runtime carries the same config module. Android uses `BuildConfig.ASSISTANT_PUBLIC_URL`, set at APK build time from `ASSISTANT_PUBLIC_URL`, so the public endpoint is no longer duplicated in Kotlin.


## Default network configuration
Server deployment endpoints and ports are edited in `config/network.json`. The desktop companion standalone runtime mirrors the same defaults in `desktop-companion/runtime/config/network.json`. Environment variables are optional deployment overrides; if absent, the JSON values are used, with built-in constants retained only as final safety defaults.


## Headless server boundary

The server does not enumerate or open microphone/speaker devices and does not depend on a desktop GUI toolkit. Companion clients own local audio capture, playback, and user-interface presentation. The server may process PCM data received from companions, but that does not require local audio hardware.


## Language compatibility boundary

Project-facing documentation, comments, prompts, logs, UI text, and examples are English-only. Multilingual input aliases required for natural-language compatibility are isolated from orchestration code in `core/language_compat.py`. This keeps the project text consistent without removing the ability to understand supported non-English commands.

## Headless installation boundary

The root Python environment is the server environment. It must not require a display server, local microphone/speaker stack, camera, screen capture, keyboard/mouse automation, or desktop window APIs. Those dependencies belong to desktop companions. Linux server setup uses a project-local virtual environment when necessary so Debian-family distributions, including Armbian, are not forced to modify an externally managed system Python.

Server-side Playwright automation is an optional extra and is not part of the base headless installation. This keeps ARM deployments independent from browser-binary availability.


## Operation-aware origin routing

Companion-originated requests preserve the origin device as the execution target for local UI and device operations. Pure backend computation can still run on the server. Mixed actions are classified by operation so a backend helper does not accidentally open, type, click, launch, or update something on the headless server. Device-local execution must continue through `call_current_device`.


## Autonomous companion UI execution

A companion is responsible for completing normal UI workflows on its own device. JARVIS uses an inspect -> act -> verify loop instead of asking the user to position a cursor or manually navigate ordinary application UI. If a target is not visible, JARVIS can inspect, scroll, navigate, search, type ordinary text, select controls, and re-inspect until the requested state is reached.

Automation pauses only at the credential boundary (PIN/password/passcode/authentication) or when the companion genuinely lacks a required capability. After authentication is completed by the user, JARVIS re-inspects the existing session and resumes the unfinished task.

## Application-agnostic device automation

Device automation is capability-driven rather than application-driven. Application/package names and domain values are target data only. The companion exposes generic primitives for launch/close, UI inspection, click/tap, ordinary text entry, scrolling, supported global navigation, and verification.

The same inspect -> act -> verify loop applies to every application, including applications installed after MARK-LIV was built. Legacy actions may perform backend computation but do not define companion UI behavior. Credential/authentication input remains the intentional user-intervention boundary apart from a genuinely unavailable capability.

## Conversation lifecycle versus server lifecycle

Conversation lifecycle and server lifecycle are separate. Ending or closing a conversation only completes the current conversational session; it does not stop the JARVIS process, server, remote access, or paired companions. Server shutdown is a separate privileged lifecycle action and is selected only from explicit server/service shutdown intent.

## Documentation synchronization status

This document describes the current server/companion architecture. The root `readme.md` is the operational entry point and `PATCH_NOTES.md` is the version history. Current invariants are: headless server; companion-only conversational audio; origin-first routing; application-agnostic inspect -> act -> verify device automation; credential input protection; conversation lifecycle separate from server lifecycle; explicit-only scheduling; and no claim of full cross-device file sharing until a common transfer protocol exists across companions.

## Companion voice transport recovery

Interactive voice output is owned by the companion that owns the live interaction. The server relays model PCM to that companion and does not use server-local speaker output.

Android voice playback is a recoverable transport resource rather than a process-lifetime assumption. Before streaming PCM, the companion validates the current `AudioTrack`. If Android reports a dead or invalid playback object, the companion releases the stale player, creates a new initialized streaming player, and retries playback. This prevents a stale platform audio object from requiring an application process restart.

Unexpected companion WebSocket closure or failure performs transport cleanup:

```text
unexpected transport loss
        -> stop companion microphone stream
        -> release stale AudioTrack
        -> clear the stale WebSocket reference
        -> schedule companion reconnect
        -> authenticate/re-establish device transport
        -> recreate playback state when new audio arrives
```

Authentication revocation is not auto-recovered as an ordinary transport failure; the companion returns to pairing as required.

Intentional conversation end is separate from unexpected transport recovery. When the user ends the conversation, the companion stops microphone capture, releases playback resources, closes the current conversation socket, and remains in the explicit ended state. It must not immediately reconnect merely because the user intentionally ended that conversation.

Voice routing and command routing remain separate. `call_current_device` targets the origin/current companion. `call_paired_device` is used for another explicitly targeted paired device and requires an exact discovered device identifier; aliases or placeholders for the current device must not be used as paired-device IDs.

The recovery path is transport-generic and does not depend on the application currently open on the companion.

## Live transcript streaming and rollover recovery

Live input/output transcription is broadcast as `transcript.delta` while audio is still flowing. Companion clients render the current cumulative turn and replace it with the final `log` entry at `turn_complete`; progress/status events remain outside the transcript. If the provider session expires or the receive task fails before `turn_complete`, the server records bounded `You [partial]`/`JARVIS [partial]` entries, disables phone audio immediately, drains the phone queue, and reconnects with the preserved context. This keeps provider rollover separate from the authenticated device WebSocket.


`runtime/error.log` is reserved for actionable diagnostics rather than a complete runtime transcript. The detached headless worker filters normal stdout so routine INFO/debug events, successful device/tool operations, connection-state chatter, and user/assistant transcript lines are not persisted in the error file.

Warning/error-like stdout diagnostics are retained. Python stderr is written directly to the same rotating sink so exceptions and tracebacks remain complete. The error sink keeps the existing bounded size-based rotation and backup limits.

MARK-LIV does not create a second persistent full-runtime transcript as part of this change. Normal runtime output remains ephemeral unless a dedicated diagnostic facility explicitly captures it.

## Intentional voice termination state

Voice recovery distinguishes intentional session end from unexpected transport failure. End-call first sets explicit intentional-end state, then stops audio and closes the WebSocket. Close/failure callbacks cannot reconnect while that state is active. Unexpected failures still permit automatic reconnect. A new explicit voice connection clears the state.

## Server browser capability and origin routing

`browser_control` is a server action, so Playwright is installed with server requirements. Browser binaries are platform runtime dependencies: setup installs Chromium on x86_64 desktop-class hosts and does not force browser binaries onto ARM/headless hosts. Companion-origin UI/vision remains capability-driven and on the origin companion unless server/host is explicitly targeted.

## Host browser runtime policy

Server-side `browser_control` depends on the Playwright Python API but not on Playwright-managed browser binaries. Browser executables are host capabilities. Interactive automation may start only when the requested browser resolves to a host executable or an explicit supported installed-browser channel. Missing browsers are reported as unavailable; MARK LIV does not silently substitute bundled Chromium.

This policy is independent of origin routing: companion-origin browser/UI operations remain on the originating companion unless the user explicitly targets the server/host.

## Generic task continuity

Task continuity is application-agnostic and separate from conversational session resumption. `runtime/active_task.json` is written atomically and contains only the active task state/checkpoints needed for recovery. Multi-step work begins through the `task_continuity` Live tool; operational tool start/results are recorded automatically. On a new Live connection, unfinished state is injected into context and a continuation turn is scheduled. External state must be inspected/reconciled before stale checkpoints are trusted. Tasks pause at credential/user-only authentication boundaries and complete only after end-state verification.
## Vision and file-storage boundary

Visual analysis requires real image bytes. All camera-capable companions use the same `camera.capture` contract. Android provides one-shot front/back JPEG capture through Camera2. The shared Windows/Linux/macOS desktop companion provides one-shot JPEG capture from its configured/default host webcam through OpenCV and reports `default` when the host camera has no reliable front/back semantic. `android.ui.inspect` remains structured accessibility data and is never a vision substitute. Camera applications do not need to be launched for capture.

Server transfer storage is project-local and single-copy: content is addressed by SHA-256 under `storage/objects/`, while transfer/name state is metadata. Upload, share, and download are not separate physical copies. Cross-companion transfers use short-lived one-time HTTP tickets so bytes stream outside the WebSocket control channel. The server verifies source upload hash/size and queues a durable attachment reference for the destination, even if offline. The recipient chooses when to download, open, save, or share; download and save are verified separately. Temporary objects expire with their final inbox reference after 30 days unless the user explicitly requests permanent server retention. Legacy `storage/uploads`, `storage/share`, and `storage/downloads` files are ingested into the object store on startup. The entire `storage/` tree is runtime data and excluded from Git.



### Vision origin continuity
Companion-origin vision remains bound to the originating paired device across transient WebSocket reconnects. Missing/offline companion vision never falls back to server camera or screen hardware. Server/host visual capture requires an explicit user request for server/host hardware.


### Android camera capture readiness
Android `camera.capture` performs a bounded Camera2 3A warm-up before still capture so exposure, white balance, and focus can settle. This is internal to the Android companion and does not change the generic `camera.capture` capability contract shared with desktop companions.


### Explicit re-pair replacement
A normal disconnect never deletes trust. An explicit Pair Code may replace a stale identity created by reinstalling a companion. Replacement is automatic only when exactly one non-revoked, offline trusted record has the same companion-reported name; ambiguous same-name records are preserved. The new identity, capabilities, origin affinity, and voice affinity then become authoritative. This rule is platform-neutral for Android, Windows, Linux, and macOS companions.


### Live vision session binding and action rejection guard
Captured vision bytes are scoped to the Live connection generation that produced the tool result. A reconnect invalidates pending bytes from the previous generation; the task may continue, but rejected/stale media payloads are not replayed blindly. Device automation also records an exact rejected `(device, capability, arguments)` signature. The same rejected action cannot execute unchanged again until the device is re-inspected, the plan changes through a different successful action/arguments, or a new user turn begins. This rule is shared across Android and Desktop companion routing.


### Deferred attachment selection and companion controls (v60.10)
Interactive voice file selection is asynchronous: JARVIS completes its spoken instruction before the source companion opens its native file picker. The selected file then continues through the existing single-copy SHA-256 attachment pipeline. Android exposes dedicated Attachments and Device Control actions; Device Control always delegates enablement to Android Accessibility Settings and never enables the service silently. Attachment transfer failures are logged as diagnostics without file contents or one-time transfer tokens.


### Overflow companion menu and final-turn attachment picker (v60.11)
Android keeps the main voice surface uncluttered: Attachments and Device Control are grouped under the top-right overflow menu. Each destination opens a richer status/action dialog instead of occupying the app bar. Deferred attachment selection no longer uses transient SPEAKING/LISTENING state changes. The runtime emits `assistant.turn.complete` only after the completed Live turn has drained from the companion audio queue; Android and Desktop release a pending native file picker only on that event. Attachment lifecycle diagnostics use warning/error severity markers so detached-server `runtime/error.log` retains picker queued/selected/cancelled, transfer complete, and transfer failure checkpoints without file contents, local source paths, hashes, or transfer tokens.


### Single-request attachment transaction and companion-styled menus (v60.12)
A Live user turn owns at most one attachment transaction for a source/destination pair. Once native selection is queued, repeated `transfer_file` calls in the same user turn—including model-generated content URIs—reuse the existing transaction status and cannot open another picker or upload another file. The server records completion/failure/cancellation for that request so a retry receives the real outcome rather than starting over. Android companion submenus now follow the main dark/cyan visual language with circular action icons, clearer status copy, and middle-ellipsized filenames that keep the file extension visible.


### Multi-file attachment batches (v60.13)
A single explicit attachment request may select multiple files in one native picker. Android uses `ACTION_OPEN_DOCUMENT` with multi-selection enabled; Desktop uses its native multi-file picker. The selection is sent as one logical batch transaction, while every selected file remains an independent durable attachment in the recipient inbox and single-copy object store. Batch results report total/completed/failed counts and per-item results. Partial failure does not reopen the picker or retry the whole batch. The one-transaction-per-user-turn guard remains in force.


### Android companion panel (v60.20)

The Android companion renders overflow navigation and attachment actions within one dialog view. This is a client presentation change; attachment routing and server storage contracts are unchanged.

### Explicit server storage destination (v60.19)

The transfer_file tool accepts source_device=current and destination_device=server. The server forces permanent object storage and creates a durable file alias for each upload, adding a numeric suffix on filename collisions. It records read-only sender history without creating a recipient inbox entry or starting an assistant edit task. On startup, previous self-routed uploads with available objects are promoted to permanent server aliases and reclassified as server storage. Companion destinations continue to use recipient inbox references and recipient-controlled saving.

### Assistant uploads and delivery completion (v60.18)

A transfer whose source and destination are the same authenticated companion is an assistant upload. Its verified object is retained in the sender history and excluded from the recipient inbox; a named hard link supplies the existing file tools with an extension-bearing path. Other-device transfers create recipient inbox entries. Completed batches inject a Live continuation to report delivery or resume the original requested work.

### Voice attachment turn boundary (v60.17)

Input transcription resets the per-turn attachment guard before the model invokes tools. Paired-device discovery and transfer_file with an omitted source queue the native picker after the assistant turn.

### Attachment transfer and Live session recovery (v60.15)

The source companion supplies the displayed filename for opaque Android document URIs. Picker events are accepted only from the source device; selected batches enter a transferring state. Gemini Live 1011 triggers transient reconnect.

### Attachment picker diagnostics and duplicate-name routing (v60.14)
Attachment picker delivery now has explicit `received` and `opened` acknowledgements, persisted by the server diagnostic logger. Android and Desktop remember whether the current assistant turn has already completed, so a picker request arriving immediately after the completion event is opened once instead of waiting forever for an event that already occurred. SPEAKING/THINKING resets that completion latch for the next response.

Device-name resolution now prefers an exact device ID. When several non-revoked records share the same display name, exactly one currently-online match may be selected; multiple online matches remain ambiguous and are never guessed. Historical trust records are not silently deleted because identical model names can represent different physical devices.

## Companion visual identity

The desktop companion renders the original animated reactor core without the face mesh or avatar renderer. Android uses the same dark/cyan visual language for voice, pairing and attachment tabs. These UI assets live exclusively in companions; the server remains headless.

The desktop companion handles pairing asynchronously, verifies TLS for public endpoints, and routes binary WebSocket frames exclusively to voice playback. The server reports denied device capabilities as tool results without changing device permissions. Its rotating error log excludes successful transfer and zero-rejection discovery records.
