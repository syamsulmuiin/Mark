## v60.5 - Companion camera default parity

- Audited Windows, Linux, and macOS camera capture for parity with the Android default-camera policy.
- Desktop camera capture does not force exposure, brightness, contrast, saturation, hue, color effects, or grayscale settings; host OpenCV/backend and camera vendor defaults remain authoritative.
- Replaced the fixed desktop 10-frame delay with a bounded 12-frame valid/stability warm-up while leaving all camera properties untouched.
- BGR-to-RGB conversion remains only for correct color channel ordering when encoding with PIL; it is not grayscale processing.
- Android keeps Camera2/HAL template defaults with bounded warm-up. The shared `camera.capture` result contract is unchanged across companions.
- No source files removed.

## v60.4 - Android camera exposure warm-up

- Camera warm-up and still capture now use the device Camera2/HAL template defaults without forcing AE, AWB, AF, color effects, or grayscale modes.

- Fixed Android camera captures that could be black or severely underexposed, especially after switching to the rear camera.
- Camera2 now runs a bounded preview-style 3A warm-up with auto exposure, auto white balance, and continuous autofocus before the still JPEG capture.
- Capture proceeds after 3A convergence or a bounded frame limit, preserving deterministic completion.
- Companion routing, voice, UI, desktop camera behavior, and server behavior are unchanged.
- No source files removed.

## v60.3 - Companion vision origin continuity

- Fixed companion vision requests falling through to headless server screen/camera capture after a transient companion WebSocket disconnect.
- Companion origin affinity now survives transient disconnects; device calls still require the paired device to be connected.
- Server camera/screen capture is no longer a fallback when companion origin is missing.
- Server/host hardware vision runs only when the user explicitly requests server/host camera or screen.
- Tightened explicit server/host intent detection so merely mentioning the word server does not redirect companion vision.
- No source files removed.

## v60.2 - Android build fix

- Fixed Android companion Kotlin compilation after camera capture support.
- Kept URL-safe Base64 for device identity/signatures separate from Android JPEG Base64.
- Made persisted device identity values explicitly non-null after initialization.
- Kept `camera.capture` behavior and all v60/v60.1 functionality unchanged.
- No source files removed.

## v60 - Generic camera capture across all companions

- Extended the generic `camera.capture` contract from Android to the shared Windows/Linux/macOS desktop companion.
- Desktop pairing and WebSocket proof now advertise `camera.capture`, and capability calls return real JPEG bytes using the existing local OpenCV capture path.
- Desktop webcams report their actual generic selection as `default` instead of pretending a requested front/back identity; Android keeps real front/back selection through Camera2.
- Fixed desktop camera backend selection when no OS config exists: Windows, Linux and macOS are now detected from the host instead of silently defaulting to Windows.
- Preserved v59 real-image validation, project-local server storage, Git exclusion, generic routing, and v58 persistent task continuity.

## v59 - Real companion camera vision and project-local storage

- Replaced the invalid Android vision fallback that treated `android.ui.inspect` accessibility text as if it were image capture.
- Added Android `camera.capture` with real JPEG bytes and explicit front/back selection using Camera2; the Camera application does not need to be opened.
- Server vision now validates and injects real image bytes before answering camera questions; companion capture is intentionally one-shot and does not launch the Camera app.
- Moved server transfer storage to project-local `storage/uploads`, `storage/share`, and `storage/downloads`; directories are created automatically and `storage/` is ignored by Git.
- Kept upload source selection user-directed and companion save destinations local/user-selected.
- Restored native-companion access to authenticated upload/list/download routes that were accidentally blocked by the native-only HTTP middleware.
- Removed the stale internal installer path that still downloaded Playwright Chromium.
- Reviewed the supplied runtime log: resumption-handle rejection recovered normally; two generic `scroll` calls were rejected. `call_current_device` now normalizes generic inspect/click/text/scroll/global aliases to the matching advertised Android UI capability when available. There was no camera traceback because prior Android builds had no camera capability.

## v58 - Generic persistent task continuity

- Added application-agnostic persistent unfinished-task state.
- Multi-step tasks can persist goal, constraints, completion criteria, verified checkpoints, blockers, origin device, and last operational action/result.
- Operational tool calls are journaled automatically while a persistent task is active.
- Live reconnect, rollover, rejected resumption handles, interrupted sessions, and server restart can restore and automatically continue unfinished work.
- Recovery requires inspection/reconciliation of external state and does not treat stale UI state as proof.
- Credential/user-authentication boundaries pause the task instead of completing or discarding it; reconnect does not auto-run a WAITING task.
- Task completion requires verified requested end state.
- Continuity is generic and does not branch on application or task type.
- Preserved v57 browser/runtime, origin-routing, error-log, and intentional voice-end fixes.

## v57 - Host-browser runtime correction

- Built from v56.
- Removed automatic `playwright install chromium` from server setup.
- Kept the Playwright Python package as a normal server dependency because `browser_control` is discovered and imported at runtime.
- Interactive browser automation now requires the requested host browser to resolve to an installed executable or supported installed-browser channel.
- Prevented silent fallback to a Playwright-managed bundled browser when a requested host browser is missing.
- Linux browser user-agent metadata now uses the detected machine architecture instead of hard-coded x86_64.
- Preserved v56 origin-device routing, runtime-log filtering, English-only browser error text, and the v54 intentional voice-end lifecycle fix.
- Synchronized README and server/client architecture documentation.

## v56 - Playwright dependency and origin-routing alignment

- Built from v54 and preserved the intentional voice-end lifecycle fix.
- Playwright Python runtime is now installed with normal server requirements because browser_control imports it during discovery.
- Setup installs Chromium automatically on x86_64 Windows/Linux/macOS and does not force browser binaries onto ARM/headless hosts.
- Preserved generic companion-origin vision routing and prevented silent server hardware substitution.
- Removed application-specific fallback guidance.
- Replaced the non-English browser platform error with English in server and desktop runtime copies.
- Tightened error-log transcript exclusion.
- Synchronized README, architecture, and patch notes.

## v54 - Intentional voice end lifecycle fix

- Fixed ended voice conversations immediately reconnecting after end-call succeeded.
- Added explicit companion intentional-end state before WebSocket closure.
- Suppressed automatic reconnect for intentional end while retaining recovery for unexpected transport loss.
- A new explicit voice connection clears the ended state.
- Built from v52; v53 installer changes are not included.
- Synchronized root README, Android companion README, architecture, and patch notes.

## v52 - Severity-focused error logging

- Fixed `runtime/error.log` capturing the complete server stdout/stderr stream.
- Normal INFO/debug activity, successful tool/device operations, connection chatter, and conversation transcript are no longer persisted in `error.log`.
- Warning/error-like stdout diagnostics are filtered into `error.log`; stderr remains fully captured so Python exceptions and tracebacks are preserved.
- Kept bounded size-based rotation and existing log-size/backups configuration.
- Did not add a persistent full `runtime.log`, avoiding a second stored conversation/runtime transcript.
- Synchronized `readme.md`, `SERVER_CLIENT_ARCHITECTURE.md`, and `PATCH_NOTES.md`.

## v51 - Voice architecture documentation synchronization

- Synchronized `SERVER_CLIENT_ARCHITECTURE.md` with the v50 companion voice self-recovery implementation.
- Documented companion audio ownership, stale `AudioTrack` recovery, disconnect cleanup, automatic reconnect, authentication-revocation behavior, and intentional conversation-end behavior.
- Documented the current-device versus exact paired-device routing boundary.
- Documentation-only correction; no runtime behavior was changed from v50.

## v50 - Companion voice self-recovery

- Fixed Android interactive voice playback becoming silent until the companion process was killed and reopened.
- AudioTrack is validated before playback, recreated after dead/invalid write states, and fully released on transport disconnect/failure.
- Non-revoked companion WebSocket failures/closures schedule automatic reconnection instead of requiring an application restart.
- Intentional conversation end remains a user-controlled end state and does not itself request a reconnect.
- Added generic current-device routing guidance: current/origin companion calls use `call_current_device`; `call_paired_device` requires an exact discovered device ID.
- No application-specific automation rule was added.

## v49 - Documentation synchronization

- Rebuilt the root README as current-state documentation instead of accumulated version-specific notes.
- Synchronized the README with the headless server architecture, origin-first routing, application-agnostic device automation, credential boundary, companion-only voice, explicit-only scheduling, and conversation/server lifecycle separation.
- Documented the actual current file-handling status without claiming unsupported generic cross-device file sharing.
- Synchronized server/client architecture documentation and companion README status notes.
- Kept version history in `PATCH_NOTES.md`.
- No runtime/source behavior was changed in this documentation-only release.

## v48 - Conversation end / server shutdown separation

- Fixed the semantic boundary between ending a conversation and shutting down JARVIS.
- Conversation/session-ending intent must not invoke `shutdown_jarvis`.
- Server shutdown is reserved for explicit server/service termination intent only.
- Ending a conversation leaves the server and companions running and ready for the next conversation.
- The rule is intent-based and language-agnostic; no application-specific or language-specific recipe was added.
- Preserved v47 generic device automation and the credential boundary.

## v47 - Application-agnostic device automation

- Companion UI automation is now explicitly capability-driven rather than application-driven.
- Application/package names and domain values are target data only and do not define routing or UI policy.
- Added generic device-effect operation classification to the central origin-device router.
- Previously unseen applications use the same inspect -> act -> verify loop without a predefined recipe.
- Legacy actions remain available for backend work but must not replace generic companion UI control.
- Preserved credential protection, operation-aware routing, autonomous execution, and headless-server isolation.
- No application-specific automation recipe was added.

## v46 - Autonomous companion UI execution

- Added a generic inspect -> act -> verify execution contract for all companion applications.
- JARVIS must no longer ask the user to position a cursor, select normal UI controls, add ordinary items, search ordinary text, or complete other UI steps that the companion can perform.
- When a target is not visible on the first inspection, JARVIS must navigate, search, scroll, type, select, and re-inspect autonomously before reporting a blocker.
- Completion must be verified from companion results; JARVIS must not claim success without device evidence.
- Automation pauses only for the existing credential/authentication boundary or a genuinely missing companion capability.
- Preserved v45 operation-aware origin routing and all earlier server/headless protections.

## v45 - Operation-aware companion routing

- Extended origin-device isolation from whole-action routing to operation-aware routing.
- Preserved the existing device-local guard for browser, computer, settings, desktop, files, apps, screen, messaging, system-monitor, and YouTube actions.
- Added mixed-action classification for `code_helper`, `game_updater`, and `file_processor`.
- Device-local operations such as open, launch, type, click, press, focus, close, install, update, patch, show, preview, and print are routed to the origin companion.
- Backend-only computation remains available on the server and is not blocked merely because the request originated from a companion.
- Preserved v43 credential-input protection and v44 origin-device isolation.
- No UI feature was added or removed.

## v44 - Origin companion media isolation

- Fixed a routing omission that allowed `youtube_video` to execute on the headless server even when the request originated from a companion.
- Added `youtube_video` to the existing origin-first device-local action guard.
- Companion-originated YouTube/media workflows must continue through `call_current_device` and the origin companion capabilities instead of opening media on the server.
- Preserved the full companion control and credential-input boundary from v43.
- No unrelated runtime, UI, Android application, or scheduling behavior was changed.

## v42 - Clean source package

- Repacked v41 as a clean source distribution.
- Removed generated Python bytecode and `__pycache__` directories from the distributable package.
- Validation now checks Python source syntax without writing bytecode into the source tree before packaging.
- Preserved the v41 signed release workflow fix and the verified GitHub Actions majors.
- Preserved removal of the obsolete headless-server audio modules while retaining the desktop companion audio modules.
- No runtime feature, Android application source, server behavior, or companion behavior was changed.

## v41 - Signed release packaging reliability

- Kept the verified GitHub Actions majors introduced in v40.
- The Android debug job is unchanged because it already succeeds with the new Actions versions.
- The signed release job now uses Gradle cache in read-only mode to avoid writing or reusing release packaging state across runs.
- The signed release build now runs `clean assembleRelease --stacktrace` so stale incremental packaging output is removed and any future packaging failure exposes the full underlying exception.
- No Android application source, Gradle version, SDK level, signing secret names, or runtime behavior was changed.

# v39 — Android CI maintenance and headless server cleanup

- Updated `actions/checkout` in the Android workflow from v4 to v5. Other workflow actions remain on their currently compatible major versions pending verified upstream major releases.
- Removed obsolete server-local audio modules: `core/audio_devices.py`, `core/stt.py`, and `core/tts.py`.
- Preserved the corresponding desktop companion runtime modules under `desktop-companion/runtime/core/`.
- No runtime routing, voice relay, companion state, scheduling, or server administration behavior was changed.

# MARK-LIV current patch notes

This file replaces the obsolete notes for the former GUI/CLI/background architecture.

## Current baseline

- Headless server lifecycle with `--start`, `--stop`, `--enable`, `--disable`, and `--pair`.
- Native Android and Windows/Linux/macOS companions are the interaction surfaces.
- Interactive voice is companion-only; the server never plays local TTS.
- Origin-first routing sends device-local actions back to the companion that originated the turn unless another target is explicit.
- `origin_device_id` and `active_voice_device` are independent state.
- Paired-device name resolution prefers the online matching record and canonical device UUID.
- Android Accessibility UI automation supports inspect/click/text/scroll/global actions and uses inspect/act/verify recovery.
- Gemini Live transport/session rollover preserves active conversation context.
- News, time, and briefings are on-demand by default.
- User-created recurring workflows persist and execute only when authorized by the user.
- Self-repair is currently Diagnostic/Dry-Run only: read-only, dependency-aware, and without an arbitrary total file-count limit.

## Self-repair safety

Diagnostic mode can inspect the full relevant dependency path and propose a root-cause patch. It cannot modify/delete source, install dependencies, restart the service, or mutate Git. Production apply/rollback is intentionally not enabled yet.

## Validation expected for release packages

At minimum, compile changed Python modules with `python -m py_compile` and run ZIP integrity verification after packaging. Android/desktop source should only be reported as changed when its files actually differ; Android build success must not be claimed unless Gradle was actually run.

## v26 — conversational self-repair activation

- A vague error observation no longer authorizes `self_repair_diagnostic` automatically.
- JARVIS must acknowledge the issue and obtain a concrete symptom plus explicit diagnose/check/debug/repair intent before starting the read-only diagnostic.
- `main.py` enforces the activation rule in code as a backstop, so an accidental model tool call is rejected safely and returned to conversation instead of starting diagnosis.
- Diagnostic mode remains read-only with no apply/edit/delete/install/restart/Git capability.


### v27 runtime stability
- Headless server does not emit unsolicited CPU/RAM voice alerts; system status remains available on demand.
- Gemini side/diagnostic calls no longer open extra Live sessions that can consume Live quota or destabilize the interactive companion voice session.
- Removed retired pinned `gemini-2.5-flash` / `gemini-2.5-flash-lite` fallback names in favor of maintained rolling aliases.
- WebSocket keepalive/close timeouts are treated as transport rollover: conversation context is preserved and the server reconnects quietly.
- Diagnostic self-repair remains read-only and still requires explicit, concrete user diagnostic intent.

## v28 — quiet expected Live rollover tracebacks

- Suppresses the duplicate Python traceback emitted inside `_receive_audio()` for expected Gemini Live rollover conditions (`1008 operation was aborted`, GoAway/session-duration rollover, keepalive ping timeout, and close timeout).
- The exception is still re-raised to the existing lifecycle handler, so reconnect and conversation-context recovery are unchanged.
- Unexpected receive exceptions still print their traceback for debugging.
- Offline/connect failures such as Windows `ConnectionRefusedError` are not reclassified by this patch.

## v29 — quiet transient network recovery
- Expected Gemini Live 1008/GoAway rollover no longer prints a receive-side error line or traceback; lifecycle reconnect remains unchanged.
- Transient network failures (including Windows 1225 refused and 1236 aborted) no longer dump repeated tracebacks while offline; retry/backoff remains active.
- Unexpected/non-network exceptions still print full tracebacks for diagnostics.

## v30 — runtime modularization, centralized model config, bounded logs

- Reduced `main.py` from 2,548 to about 2,063 lines without changing Live-session behavior.
- Moved headless server lifecycle/admin CLI helpers to `core/server_lifecycle.py`.
- Moved Live-bound tool schemas to `core/live_tools.py`; file-backed actions remain auto-discovered from `actions/*.py`.
- Added `core/model_config.py` as the server-side source of truth for Gemini model identifiers. Optional environment overrides: `MARK_LIV_LIVE_MODEL`, `MARK_LIV_TEXT_MODEL`, `MARK_LIV_TEXT_FALLBACK_MODEL`.
- Kept the desktop companion standalone by mirroring the same model-config module inside its packaged runtime; Android does not embed Gemini model identifiers.
- Added `core/runtime_log.py`. The server worker now owns `runtime/error.log` and rotates it at 5 MiB with five backups by default instead of allowing one file to grow forever. Optional overrides: `MARK_LIV_LOG_MAX_BYTES` and `MARK_LIV_LOG_BACKUPS`.
- The launcher no longer leaves an inherited Windows file handle on `error.log`, allowing atomic rollover while the worker is running.
- No user-facing features, routing behavior, voice behavior, reconnect policy, or scheduling cadence were changed.

## v31 — Optional dashboard dependency startup fix
- Dashboard import/initialization failures no longer terminate the core JARVIS runtime.
- Missing optional dashboard dependencies now disable the dashboard and allow the core runtime to continue.
- Dashboard port ownership conflicts remain fatal intentionally, preserving the single-server-worker protection.
- No companion protocol, voice routing, Gemini lifecycle, scheduling, or tool behavior was changed.

### v32 network configuration centralization
Network endpoints and ports now use `core/network_config.py` as the server source of truth. Defaults remain unchanged, but deployments can override them with `MARK_LIV_PUBLIC_HOSTNAME`, `MARK_LIV_DASHBOARD_PORT`, `MARK_LIV_LAN_HTTPS_PORT`, `MARK_LIV_DISCOVERY_PORT`, and `MARK_LIV_LOCAL_HOST`, or `config/network.json`. The standalone desktop runtime carries the same config module. Android uses `BuildConfig.MARK_LIV_PUBLIC_URL`, set at APK build time from `MARK_LIV_PUBLIC_URL`, so the public endpoint is no longer duplicated in Kotlin.

## v33 — explicit default network config

- Added `config/network.json` to the package as the normal editable network configuration.
- Preserved the existing deployment values: `auth.kasirdigital.web.id`, ports `8000`, `8001`, `37991`, and local host `127.0.0.1`.
- Added the same default JSON to the standalone desktop companion runtime.
- Environment variables are still supported only as optional highest-priority overrides.
- Resolution order: environment override → JSON config → built-in safety default.
- No runtime routing, pairing, voice, dashboard, or reconnect behavior was changed.


## v34 — True headless server dependency split

- Removed the server runtime's top-level `sounddevice` import.
- Removed server-side audio-device configuration and enumeration. Microphone and speaker hardware are companion responsibilities.
- Removed `PyQt6` and `sounddevice` from the root/server `requirements.txt`.
- Kept desktop companion audio dependencies in `desktop-companion/requirements.txt`.
- The server continues to process and relay companion PCM audio without opening local audio hardware.
- No server GUI dependency is imported or installed on the server startup path.
- No files were removed.


## v35 — English-only project text audit

- Replaced remaining Indonesian examples in `readme.md` with English examples.
- Rewrote self-repair examples in `core/prompt.txt` in English.
- Moved non-English diagnostic input aliases out of `main.py` into `core/language_compat.py`.
- Non-English literals in `core/language_compat.py` are intentional compatibility data only; they preserve natural-language command recognition and are not project-facing documentation, comments, logs, prompts, or UI text.
- Runtime behavior, routing, voice, companion execution, and self-repair safety semantics are unchanged.

## v36 — Cross-platform headless server setup

- Added OS and CPU-architecture reporting, including normalized ARM64/aarch64 detection.
- Linux setup now creates and uses a project-local `.venv` when needed, avoiding PEP 668 system-Python installation failures on Debian/Ubuntu/Armbian.
- Reduced root `requirements.txt` to headless server dependencies.
- Moved desktop input, screen, camera, and local-control dependencies to `desktop-companion/requirements.txt`.
- Moved Playwright to the optional `requirements-browser.txt` server extra and stopped automatic browser-binary installation.
- Removed desktop/audio post-install instructions from the server installer.
- No existing source file was removed.

## v37 — Quiet recovery for abnormal WebSocket closure

- Treats Gemini Live WebSocket `1006 abnormal closure` as a transient transport failure when the underlying connection disappears without a close frame.
- Recognizes Windows network failures `WinError 64` and `WinError 121` as transient transport conditions.
- Suppresses duplicate receive-side and TaskGroup tracebacks for these expected connectivity failures while preserving reconnect/backoff and local conversation-context recovery.
- Unexpected application errors still retain full tracebacks.
- No companion routing, audio lifecycle, scheduling, tool behavior, or server administration behavior was changed.


## v38 - Companion Thinking State
- Added an event-driven `THINKING` voice state for Android and desktop companions.
- Voice state flow is `LISTENING -> THINKING -> SPEAKING -> LISTENING`.
- `THINKING` is emitted only when Gemini produces pre-audio model content or while a tool call is being executed; no cosmetic delay timer was added.
- Existing microphone streams remain alive across state changes.
- Preserved the v37 transient network recovery behavior.

## v40 - Verified Android GitHub Actions majors

- Verified the latest upstream releases before changing the workflow: actions/checkout v7.0.1, actions/setup-java v6.0.1, gradle/actions v6.3.0, and actions/upload-artifact v7.0.1.
- Updated `build-android.yml` to the corresponding maintained major tags: `checkout@v7`, `setup-java@v6`, `setup-gradle@v6`, and `upload-artifact@v7`.
- Android application source, Java 17, Android SDK 35, Gradle 8.10.2, signing, and artifact paths are unchanged.
- Python Quality CI remains intentionally on hold.

## v43 - Full companion control with credential boundary

- Companion-origin requests now explicitly continue autonomous device UI execution for ordinary user-authorized actions, including navigation, text entry, selection, Send/Submit, and verification.
- Android Accessibility inspection marks credential fields and Android text entry hard-blocks password/PIN/passcode/credential fields before input.
- Desktop companion local execution blocks operations that explicitly target credential fields or credential data types.
- Password generation through computer control is blocked on both server and desktop runtime copies.
- When authentication is encountered, automation preserves the current session/state and waits for user instruction instead of navigating away or handing ordinary UI work back to the user.
- No credential is typed, pasted, generated, inferred, or submitted by MARK-LIV.

## v60 packaging hygiene correction
- Removed accidental empty root `__pycache__/` directory from the distribution package.
- Packaging validation now treats Python caches, bytecode, virtual environments, IDE/test caches, runtime logs/state, build outputs, and project-local `storage/` contents as forbidden distribution artifacts.
- No runtime behavior changed from v60.
