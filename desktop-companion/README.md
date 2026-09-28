# MARK-LIV Desktop Companion

Native companion runtime for Windows, Linux, and macOS. The original MARK LV PyQt HUD, standard animated reactor core, metrics, and activity log now live in the desktop companion. Original HUD components are licensed under the project CC BY-NC 4.0 license. It is the desktop user-facing control/execution surface for the headless MARK-LIV server and carries the established local action runtime so device-local commands execute on this computer.

## Install and run

```bash
python desktop-companion/install.py
python desktop-companion/companion.py
```

Pair the companion with a running server using a Pair Code created by:

```bash
python main.py --pair
```

## Routing

A command originating from this companion defaults to this computer unless the user explicitly targets another paired device or the server. Cross-device requests use the trusted device mesh. Interactive voice input/output also stays on the companion; the server does not use a local microphone or speaker.

## Local runtime

`local_runtime.py` and `runtime/` preserve desktop-side action support. Android-only `android.ui.*` behavior is not copied to desktop. Platform-specific actions remain subject to OS capabilities and permissions.

## Current MARK-LIV control model

The desktop companion is a device endpoint for the headless MARK-LIV server. Device UI work is origin-first and application-agnostic: application names are target data and generic local capabilities perform the operation.

Credential entry remains protected. Ending a conversation does not stop the server. The existing local file controller manages the desktop filesystem; it is not a generic companion-to-companion file-transfer protocol.



## Camera vision

Windows, Linux and macOS advertise the same native `camera.capture` capability. The shared runtime captures a one-shot frame from the configured/default host webcam with the platform-appropriate OpenCV backend and returns real JPEG bytes to the server. Desktop webcams are reported as `default` unless an explicit mapping exists; the companion never guesses a front/back identity. A camera application does not need to be opened. Desktop capture leaves exposure, white balance, focus, brightness, contrast, saturation, hue, and color effects at host/vendor defaults; it only performs a bounded frame warm-up before returning the JPEG.


### Re-pair identity replacement
A fresh explicit Pair Code can replace one unambiguous offline stale identity with the same companion-reported name after reinstall. Normal reconnect does not delete trust, and ambiguous same-name devices are never removed automatically.

## File transfer
The desktop companion advertises generic `file.upload` and `file.receive` capabilities. File bytes stream over one-time server transfer URLs and are verified by SHA-256 and byte size. Received files default to the user's Downloads directory unless a destination is explicitly supplied. Camera/file behavior is platform-neutral at the capability contract level.


### Attachment inbox
Incoming transfers appear in the companion attachment inbox, including attachments queued while this device was offline. No destination directory is selected by the sender. Open downloads a verified temporary local cache copy; Save As lets the recipient choose a local location; Share uses the native Android share sheet (desktop companions explain where the OS share-sheet integration is unavailable). The source companion can open its native file picker when the source path is omitted. Files remain on the server as single-copy objects for up to 30 days while inbox references exist, unless the user explicitly requests permanent server retention. The legacy file.receive capability remains available for compatibility but is not used by the transfer_file tool.


### Overflow companion menu and final-turn attachment picker
Android keeps the main voice surface uncluttered: Attachments and Device Control are grouped under the top-right overflow menu. Each destination opens a richer status/action dialog instead of occupying the app bar. Deferred attachment selection no longer uses transient SPEAKING/LISTENING state changes. The runtime emits `assistant.turn.complete` only after the completed Live turn has drained from the companion audio queue; Android and Desktop release a pending native file picker only on that event. Attachment lifecycle diagnostics use warning/error severity markers so detached-server `runtime/error.log` retains picker queued/selected/cancelled, transfer complete, and transfer failure checkpoints without file contents, local source paths, hashes, or transfer tokens.


### Single-request attachment transaction and companion-styled menus
A Live user turn owns at most one attachment transaction for a source/destination pair. Once native selection is queued, repeated `transfer_file` calls in the same user turn—including model-generated content URIs—reuse the existing transaction status and cannot open another picker or upload another file. The server records completion/failure/cancellation for that request so a retry receives the real outcome rather than starting over. Android companion submenus now follow the main dark/cyan visual language with circular action icons, clearer status copy, and middle-ellipsized filenames that keep the file extension visible.


### Multi-file attachment batches
A single explicit attachment request may select multiple files in one native picker. Android uses `ACTION_OPEN_DOCUMENT` with multi-selection enabled; Desktop uses its native multi-file picker. The selection is sent as one logical batch transaction, while every selected file remains an independent durable attachment in the recipient inbox and single-copy object store. Batch results report total/completed/failed counts and per-item results. Partial failure does not reopen the picker or retry the whole batch. The one-transaction-per-user-turn guard remains in force.


### Send files to server

A voice request to send files to the server opens the Desktop multi-select picker and stores the selected files permanently on the server. The Sent tab shows Stored on server; it has no recipient actions.

### Received and Sent attachments

The attachment window separates received files from read-only sent history. Open, Save As and Share remain available only for received files; uploads to MARK LIV for processing appear in Sent.

### Voice attachment picker

Voice requests can queue the Desktop native multi-select picker after the assistant finishes speaking.

### Attachment transaction status

The server records selected batches as transferring and returns the actual attachment ID for each completed file.

### Attachment picker diagnostics and duplicate-name routing
Attachment picker delivery now has explicit `received` and `opened` acknowledgements, persisted by the server diagnostic logger. Android and Desktop remember whether the current assistant turn has already completed, so a picker request arriving immediately after the completion event is opened once instead of waiting forever for an event that already occurred. SPEAKING/THINKING resets that completion latch for the next response.

Device-name resolution now prefers an exact device ID. When several non-revoked records share the same display name, exactly one currently-online match may be selected; multiple online matches remain ambiguous and are never guessed. Historical trust records are not silently deleted because identical model names can represent different physical devices.

## Desktop error log

Desktop failures are recorded in `~/.mark-liv-companion/logs/error.log` (Windows: `%USERPROFILE%\.mark-liv-companion\logs\error.log`). The log rotates at 2 MB with two backups. Connection, audio, pairing, attachment, and capability failures are recorded there; routine activity appears in the HUD log. The server has a separate `runtime/error.log`.

## Reactor visual

The desktop HUD uses the standard animated reactor core. Face mesh, avatar renderer, and lip-sync files are not shipped with the desktop companion.

## Pairing and connection diagnostics

Enter a current six-character code created by `python main.py --pair`. Invalid or expired offers display a clear message, and the desktop UI remains responsive while contacting the server. Public HTTPS requests verify the server certificate; only private LAN endpoints can use the existing self-signed transport behavior. Binary voice packets are not parsed as JSON. Desktop connection and unexpected capability failures are written to the rotating companion error log.

The desktop starts on a dedicated dark Pair Code screen with a compact reactor emblem. Paired devices reconnect with their saved identity. The main HUD appears only after the server sends `ready`; no account username or password is required.

The grouped desktop menu provides reconnect, new Pair Code, microphone mute, response interrupt, input/output audio device selection, attachments, and full screen. A remote gateway 502 triggers signed LAN discovery for an already paired device. See `DESKTOP_FEATURE_PARITY.md` at the project root for the original MARK LV control mapping and remaining server-owned controls.
