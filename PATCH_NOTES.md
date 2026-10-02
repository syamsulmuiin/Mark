## v60.36 - Live-session clean recovery diagnostics

- Captured bounded, credential-redacted provider exception details in `runtime/interaction.log` for generic Live-session failures instead of recording only `isolated_failure`.
- Generic non-retryable Live-session failures now clear the potentially stale resumption handle, preserve bounded local conversation context, notify the Companion of reconnecting state, and create a clean provider session with backoff.
- This keeps pairing/device trust intact while preventing a connected Companion from remaining silent after a failed Gemini Live session.


- Replaced the product-specific `MARK_LIV_SKIP_BROWSER_INSTALL` environment variable with generic `SKIP_BROWSER_INSTALL`.
- Audited environment/configuration identifiers used by server, Android build, desktop companion, browser runtime, and CI. Existing `ASSISTANT_*` variables are retained as the established cross-component generic assistant configuration contract; no new product-specific variable remains in the browser setup path.


- Kept `playwright` in the single root `requirements.txt`; removed the redundant `requirements-browser.txt` extra.
- First-time `setup.py` now installs isolated Chromium on supported architectures for headless server browser automation.
- Added `SKIP_BROWSER_INSTALL=1` for deployments that intentionally provide only server-side `web_search`.
- Updated architecture, README, and browser workflow documentation to remove the obsolete separate-browser-install instructions.
- Headless browser search falls back from Google's anti-automation interstitial to DuckDuckGo while preserving the encoded query and browser session.


- Server `browser_control` now selects visible mode when a desktop display is present and headless mode on display-less Linux hosts; `BROWSER_HEADLESS` can explicitly override detection.
- Browser search queries use URL encoding instead of replacing only spaces, so punctuation and non-ASCII terms are preserved.
- Added `BROWSER_SEARCH_WORKFLOW.md` describing server `web_search`, server browser automation, Android browser control, and desktop browser control as separate execution paths.
- Documented the inspect -> act -> inspect verification loop and credential boundary for both server and Companion workflows.


- Android now advertises `browser.open` and `browser.search` during pairing and reconnect capability refresh.
- Browser URLs and searches launch through the phone's installed browser; webpage interaction continues through Accessibility `inspect -> act -> inspect` using `view_id` rather than coordinates.
- HTTP/HTTPS URLs are validated before launch, and browser search queries are encoded on-device.
- `call_current_device` now documents the browser capability path so Android-originated browser requests are not routed to the headless server browser.

- Classify Live-session, Companion WebSocket, file-transfer, tunnel, and task failures into bounded actions without coupling them to product/version names.
- Persist structured runtime error events with boundary/category/action metadata; provider model failover remains separate from transport reconnect.
- Telegram is not part of this runtime boundary set; Telegram adapter isolation belongs to the Hermes Gateway layer.

- Compare the original MARK LV setup and daily controls with the split desktop runtime. Restore local mute, interrupt, audio device selection, full screen and grouped menu access; reconnect the missing YouTube action dispatcher and desktop screen-frame vision.
- Diagnose Cloudflare HTTP 502 separately from device errors. Use the existing Pair Code to try LAN pairing when the remote endpoint returns 502, and use a signed device/server discovery exchange to reconnect an already paired desktop on the LAN. Off-LAN connectivity still depends on a working server and tunnel.
- Record the architectural control mapping in `DESKTOP_FEATURE_PARITY.md`; keep account login absent. No source files were removed.

## Companion Pair Code surface
- Restyle the Android Pair Code screen and add a matching desktop entry screen based on the visual reference. Keep the v60.24 signed Pair Code protocol; no account authentication is added.
- Open the desktop HUD only after the server sends `ready`; disconnects return to the entry surface. No source files were removed.

## v60.24
- Handle expired/invalid Pair Codes, incomplete pairing offers and invalid endpoint responses on the desktop companion without a KeyError or delayed-callback NameError. Pairing requests run off the GUI thread and use normal certificate verification for public HTTPS.
- Treat binary WebSocket audio as audio only, preventing JSON/Unicode decoding errors. Reject legacy.action requests without a tool name before dispatch; report paired-device capability denials without server tracebacks.
- Use system mono fonts for the desktop HUD and system UI fonts for controls. Minimize the Android pairing card and show its status line only during pairing or when attention is needed.
- Keep successful attachment batches and zero-rejection plugin discovery out of the severity-filtered server error.log.
- No additional source files removed since v60.23; its standalone clean-once script remains applicable to installations that still contain the old face assets and purple button resource.

## v60.31 - Transcript snapshot recovery after reconnect

- Server replays the last bounded conversation entries when the companion reconnects.
- Android replaces its transcript buffer from the snapshot instead of losing visible history after a socket close.
- The visible transcript window increases from 4 to 20 entries while retaining bounded memory.

## v60.30 - Companion title and bounded thinking recovery

- Manifest application label is explicitly `Companion`, overriding the previous hardcoded `JARVIS Companion` title.
- Android exits an unproductive `THINKING` state after 60 seconds by closing only the current socket and using the guarded reconnect path; normal `LISTENING`/`SPEAKING` states cancel the watchdog.

## v60.29 - WebSocket keepalive and bounded reconnect backoff

- Android WebSocket uses zero read/write timeouts, connection retry support, and a 15-second protocol ping interval.
- Added a lightweight application heartbeat/ack in addition to the transport ping so the public tunnel path remains observable and active.
- Reconnects use bounded exponential backoff from 1.5 seconds to 30 seconds and reset only after a confirmed `ready` event.

## v60.28 - Safe audio ingress, Companion identity, and guarded diagnostic repair

- Android audio ingress no longer blocks the OkHttp WebSocket callback thread when `AudioTrack` backpressure occurs; ingress and playback use separate bounded queues so ping/close processing remains live.
- Launcher icon now uses a white `C` on the existing `#315DA8` background.
- Android application label is now `Companion`.
- Added a separate guarded diagnostic-apply action: explicit authorization, high-confidence diagnosis, exact allowlisted replacements, a total replacement-size budget instead of an arbitrary operation-count cap, Python/XML validation, atomic writes, rollback on failure, and an immutable self-repair implementation.

## v60.27 - Ignore stale Android WebSocket callbacks

- Ignore `onClosing` and `onFailure` callbacks from an old socket after a newer reconnect has taken ownership.
- Prevent stale callbacks from stopping the active microphone/playback path or clearing the current WebSocket, which could leave the conversation connected on the server but silent on the device.

## v60.26 - Device socket ownership and end-conversation icon

- Close a stale device WebSocket when a newer authenticated connection for the same paired device arrives, preventing audio/results from being routed to an old socket during reconnect.
- Strengthen the end-conversation control with a larger, thicker close mark inside the existing proportional circular button.

## v60.25 - Hermes launcher icon parity

- Set the Android Companion launcher and round launcher icon to the same blue square and white Hermes mark used by the Hermes Companion APK.
- Keep the application label and pairing-only behavior unchanged.

## v60.24 - Android transcript speaker emphasis and camera permission recovery

- Render `YOU:` and `JARVIS:` as explicit bold speaker labels in the streaming transcript while keeping cumulative deltas replaceable and deduplicated.
- Keep a pending `camera.capture` request while Android presents the camera permission prompt; execute it after approval or return a bounded denial result instead of failing the first request before permission can be granted.
- Preserve the existing device-local camera implementation and pairing-only security boundary. No camera bytes or permissions are handled by the headless server.

## v60.23
- Remove the unused desktop holographic-face renderer, mesh, model asset, and viseme module. The standard animated reactor core remains the only desktop HUD visual; update its desktop prompt accordingly.
- Replace Android Received/Sent tab fills with transparent tabs and a cyan selected underline; match text weight and contrast to the main voice surface.
- Restyle Android Pair Code with the JARVIS header, dark card, cyan action button, and consistent text/input colors. Remove the obsolete purple button background resource.
- Provide a standalone idempotent clean-once script beside the release archive for the five removed files.

## v60.21
- Restore the original MARK LV PyQt holographic HUD, animated face, telemetry, and activity panel in the desktop companion, while keeping MARK LIV server/client pairing, voice, device actions, and attachment workflows.
- Add a rotating persistent desktop error log under the companion user profile; document the distinction from the server log. Return a clear permission result for rejected device UI calls instead of printing a server traceback.
- Remove version suffixes from README section headings and move developer guidelines into CONTRIBUTING.md.
- No files removed or deprecated; companion.py is updated and hud.py, desktop_ui.py and CONTRIBUTING.md are added.

## v60.20
- Rebuilt the Android companion overflow menu as one dark panel with a compact top-right close icon and consistent header/back navigation.
- Attachments, Device Control, and received-file actions now render within the same panel rather than stacking separate dialogs or using prominent bottom Close buttons.
- Preserved the existing received/sent attachment roles, file actions, voice transfer and server storage behavior. Added small vector back/close icons matching the companion palette.
- No source files were removed or deprecated; two icon drawable files were added.

## v60.19
- Interpret an explicit voice request to send files to the server as destination_device=server with source_device=current, using the origin companion’s native picker.
- Keep server-target uploads permanently in the server object store and its existing file listing; send them to read-only Sent history, not the phone’s inbox or an automatic assistant edit task. Resolve duplicate server filenames by appending a number before the extension.
- Report the actual stored filenames after the batch finishes. Requests for another companion continue to use the recipient inbox; source and destination IDs that are identical are rejected instead of guessed.
- Update Android and Desktop upload results with the server’s stored filename. On startup, promote older self-routed attachment uploads to permanent server aliases so previously uploaded files remain accessible without selecting them again.
- No source files were removed or deprecated.

## v60.18
- Complete attachment batches with an explicit Live continuation: voice confirms a device transfer after the batch finishes; uploads to the assistant resume the original requested file task with verified server paths. Do not report an update as complete until it is performed.
- Treat source=destination as an upload to the assistant. Keep it in the sender’s read-only history and out of the recipient inbox. The server exposes a hard-linked named processing path without duplicating object bytes; links expire with the attachment record.
- Add separate Received and Sent views on Android and Desktop. Sender history has no Open, Save As or Share controls; these remain on recipient inbox entries. Android uses dark cards and cyan circular icons consistent with its main UI.
- Successful picker lifecycle and cancelled selection are informational, while failed batch items remain warnings/errors. Tighten Live resumption error matching so an unrelated TaskGroup “unhandled” error cannot masquerade as a rejected handle.
- No source files were removed or deprecated.

## v60.17
- Reset the attachment guard when voice input transcription begins, before the model invokes transfer_file; the prior reset at turn_complete occurred too late.
- Direct voice file transfers through paired-device discovery and transfer_file with an omitted source to queue the native multi-select picker.
- Keep one-picker-per-voice-turn behavior and deferred picker opening.
- No source files were removed or deprecated.

## v60.15
- Preserve Android document filenames and extensions from the source companion instead of opaque content URI segments.
- Keep one picker transaction per user turn, including retries with changed selectors; record transferring status before batch processing.
- Validate picker events against the source device, return actual attachment IDs, and log request/device IDs and failed item index.
- Treat Gemini Live error 1011 as a transient disconnection; reconnect without duplicate tracebacks or false resumption-handle rejection.
- No source files were removed or deprecated.

## v60.14
- Fixed an attachment picker event-order race that could leave a queued request waiting forever.
- Added persisted picker `received` and `opened` diagnostics on Android and Desktop.
- Kept one-request/one-picker and multi-file batch semantics from v60.13.
- Fixed runtime routing when historical non-revoked records share a device name: one uniquely-online match is selected; multiple online matches remain ambiguous.
- Historical trust records are not silently deleted solely by matching model/name.
- No source file was deleted or deprecated.

## v60.13
- Added native multi-file selection for attachment requests on Android and Desktop companions.
- One user request still creates exactly one attachment transaction and one picker.
- Each selected file remains an individual inbox attachment; files are not automatically ZIP-combined.
- Added batch completion summaries with total/completed/failed counts and per-file results.
- Partial batch failures do not reopen the picker or retry successful files.
- Preserved the v60.12 duplicate/retry guard and single-copy SHA-256 object store.
- No source file was deleted or deprecated.

## v60.12
- Fixed repeated attachment picker/upload attempts from a single Live request by binding one attachment transaction to the current user turn.
- Model retries can no longer replace a pending native selection with an invented `content://` URI; they receive the existing transaction status.
- The async picker continuation now records completed, failed, or cancelled status so a same-turn retry reports the real outcome without starting a new transfer.
- Preserved original attachment filenames/extensions; Android inbox uses middle ellipsis so long names keep their suffix visible.
- Restyled Android companion submenu and attachment actions to match the main dark/cyan UI, with circular icons and clearer status/action rows.
- Removed SHA-256 values from successful attachment diagnostic lines; file contents, local source paths, hashes, and one-time transfer tokens are not logged.
- No source file was deleted or deprecated.

## v60.11 release lint correction
- Removed the obsolete second `phoneControl` ImageButton left behind when Android Attachments and Device Control were moved into the single overflow menu.
- No lint suppression or baseline was added; the layout now has one overflow control and no duplicate resource IDs.
- Runtime behavior is otherwise unchanged from v60.11.

## v60.11
- Moved Android Attachments and Device Control back under the top-right overflow menu to keep the voice surface uncluttered.
- Improved attachment and Device Control dialogs with icons, state/size information, and clearer actions.
- Fixed deferred native file selection to wait for the explicit `assistant.turn.complete` runtime event after Live response audio drains; transient SPEAKING/LISTENING transitions no longer launch the picker.
- Applied the same final-turn picker contract to Desktop companions.
- Attachment picker/transfer lifecycle diagnostics now use persisted warning/error severity markers so detached `runtime/error.log` captures useful checkpoints without file contents, source paths, hashes, or one-time transfer tokens.
- Kept the single-copy SHA-256 object store and recipient-controlled attachment inbox semantics unchanged.
- No source file was deleted or deprecated.

## v60.10 - Deferred attachment picker and companion UI polish

- Fixed Android attachment delivery capability parity: Android now advertises `attachment.inbox` during pairing and WebSocket proof.
- File selection requested by interactive voice is deferred until JARVIS finishes the spoken prompt; selection then resumes transfer asynchronously.
- Added attachment transfer diagnostics for picker queued/cancelled, transfer completion, and transfer failure without logging file contents or transfer tokens.
- Replaced the Android text attachment button with a paperclip action icon and unread badge.
- Replaced the Android overflow-style accessibility entry with a dedicated Device Control icon and status dialog that opens the official Accessibility Settings screen.
- Polished the Desktop attachment window while preserving platform-native file selection and destination control.
- Moved Android streaming upload/download mechanics into `AttachmentTransfer.kt`; existing object store and inbox remain modular in `core/file_store.py` and `core/attachment_inbox.py`.
- No source files removed.

## v60.9 - Recipient-controlled attachment inbox

- Changed cross-companion delivery from automatic destination Downloads writes to a durable recipient-scoped attachment inbox. The server queues attachments even when the recipient is offline; reconnect synchronizes its inbox.
- Added native attachment inbox entry points to Android and Windows/Linux/macOS desktop companions. The recipient chooses Open, Save As, or Share; Android uses the system document picker/share sheet, and desktop Save As uses the native save dialog. Desktop Share explains the native share-sheet limitation rather than silently pretending to share.
- The source companion opens its native file picker when a transfer has no accessible source path/URI.
- Preserved streaming HTTP one-time tickets, single-copy SHA-256 deduplication, destination isolation, byte/hash verification, and explicit permanent server storage. Recipient save is not inferred from delivery.
- Attachment references survive server restart and expire after 30 days; temporary objects are deleted only after the final reference expires. Existing server-retained aliases are not removed by inbox cleanup.
- Legacy file.receive remains available for compatibility but the transfer_file tool now delivers through attachment.inbox, without forcing a destination folder.
- No source files removed.

## v60.8 - Single-copy cross-companion file transfer

- Replaced physical `storage/uploads`, `storage/share`, and `storage/downloads` copies with a SHA-256 object store under `storage/objects` plus metadata.
- Legacy transfer files are ingested into the object store on startup and their redundant legacy copies are removed after hashing.
- Added generic `file.upload` and `file.receive` capabilities to Android and Windows/Linux/macOS companions. Android 10+ receives into `Downloads/MARK-LIV`; older Android returns explicit unsupported for shared-Downloads receive without legacy storage permission.
- Added `transfer_file` orchestration with one-time HTTP transfer tickets; large file bytes are streamed instead of base64-encoded through WebSocket.
- Source upload, server object, and destination are verified by SHA-256 and byte size before success is reported.
- Transfer-only server objects are deleted after verified destination receipt; `keep_on_server=true` retains one durable server object.
- Existing `/api/upload`, `/api/files`, and `/uploads/{filename}` remain compatible but now reference the single object store.
- No source files removed.

## v60.7 - Live vision validation and device action loop guard

- Bound pending vision frames to the Live session generation that captured them; stale frames are dropped after reconnect instead of being replayed.
- Added image payload validation immediately before Live vision injection (non-empty bytes, supported image MIME, bounded size).
- Added a generic device-action circuit breaker for current-device and paired-device calls: an unchanged rejected action is not executed again until the state is re-inspected, a different successful action changes the plan, the arguments change, or the user starts a new turn.
- Kept the guard platform-neutral and capability-neutral; Android and Desktop companion calls use the same failure semantics.
- Camera defaults, pairing replacement behavior, UI, and voice routing are unchanged.
- No source files removed.

## v60.6 - Explicit re-pair stale-device replacement

- Explicit Pair Code pairing now replaces one unambiguous offline stale record with the same companion-reported name when a reinstall creates a new device identity.
- Pairing with the same device identity continues to update the existing record in place.
- Automatic replacement is skipped when multiple same-name stale devices exist, preventing the server from guessing which trusted device to remove.
- Normal disconnect/reconnect never removes pairing trust.
- Runtime origin and voice affinity are reconciled from the replaced stale identity to the newly paired identity.
- The replacement rule is shared by Android and Desktop companions and does not branch on OS, application name, or package name.
- No source files removed.

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

## v60.25 - Mark source capability synchronization

- Added proactive provider-session rollover at 120 seconds, before the observed ~155-second Gemini hard expiry, so conversations recover through a controlled context-preserving reconnect instead of an abrupt provider close.
- Fixed silent voice turns by making the companion relay's explicit `ActivityStart`/`ActivityEnd` boundaries the sole turn detector; Gemini automatic activity detection is no longer mixed with manual boundaries.
- Removed the pairing-page overflow menu so transfer/file controls are unavailable before pairing.
- Replaced the conversation end phone icon with an X close icon.
- Added Android reconnect de-duplication so simultaneous `onClosing`/`onFailure` callbacks cannot create competing device sockets.
- Increased Android PCM playback buffering and stopped dropping audio chunks when the queue briefly fills, preventing audible sentence gaps during bursty Gemini output.
- Added parallel `transcript.delta` delivery for live input/output speech while audio is still streaming.
- Preserved unfinished input/output as explicit partial transcript entries on provider rollover and disabled/drained phone audio immediately when the receive loop fails.
- Updated Android transcript rendering to replace the current streaming turn with the final transcript instead of adding duplicate fragments.
- Added desktop-companion-local `video_player` parity for local files, direct media URLs, YouTube links/searches, stop, mute, and unmute.
- Kept video resolution and Qt Multimedia playback on the paired desktop companion; the headless server does not gain PyQt or `yt-dlp` dependencies.
- Added cancellation tokens so stopping a YouTube resolution prevents a late video from opening.
- Fixed explicit one-shot Live compatibility calls to select the first healthy configured Live model instead of always forcing the primary model.
- Updated the Desktop Companion dashboard layout to match the Mark desktop UI structure more closely: canonical header with identity and clock, system-monitor rail, central HUD, activity rail, command input, interrupt/microphone/attachment controls, and wired settings/control menus.

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
- Added `core/model_config.py` as the server-side source of truth for Gemini model identifiers. Optional environment overrides: `ASSISTANT_LIVE_MODEL`, `ASSISTANT_TEXT_MODEL`, `ASSISTANT_TEXT_FALLBACK_MODEL`.
- Kept the desktop companion standalone by mirroring the same model-config module inside its packaged runtime; Android does not embed Gemini model identifiers.
- Added `core/runtime_log.py`. The server worker now owns `runtime/error.log` and rotates it at 5 MiB with five backups by default instead of allowing one file to grow forever. Optional overrides: `ASSISTANT_LOG_MAX_BYTES` and `ASSISTANT_LOG_BACKUPS`.
- The launcher no longer leaves an inherited Windows file handle on `error.log`, allowing atomic rollover while the worker is running.
- No user-facing features, routing behavior, voice behavior, reconnect policy, or scheduling cadence were changed.

## v31 — Optional dashboard dependency startup fix
- Dashboard import/initialization failures no longer terminate the core JARVIS runtime.
- Missing optional dashboard dependencies now disable the dashboard and allow the core runtime to continue.
- Dashboard port ownership conflicts remain fatal intentionally, preserving the single-server-worker protection.
- No companion protocol, voice routing, Gemini lifecycle, scheduling, or tool behavior was changed.

### v32 network configuration centralization
Network endpoints and ports now use `core/network_config.py` as the server source of truth. Defaults remain unchanged, but deployments can override them with `ASSISTANT_PUBLIC_HOSTNAME`, `ASSISTANT_DASHBOARD_PORT`, `ASSISTANT_LAN_HTTPS_PORT`, `ASSISTANT_DISCOVERY_PORT`, and `ASSISTANT_LOCAL_HOST`, or `config/network.json`. The standalone desktop runtime carries the same config module. Android uses `BuildConfig.ASSISTANT_PUBLIC_URL`, set at APK build time from `ASSISTANT_PUBLIC_URL`, so the public endpoint is no longer duplicated in Kotlin.

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
- Server browser automation is now a normal first-time setup capability: Playwright remains in the single root `requirements.txt`, and setup installs isolated Chromium where supported.
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
