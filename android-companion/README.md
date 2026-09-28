# MARK-LIV Android Companion

The Android companion is a native control, execution, and interactive-voice endpoint for the headless MARK-LIV server. Android-originated device-local requests default back to this phone unless the user explicitly targets another paired device.

## Build

Open `android-companion/` in Android Studio with JDK 17 and build/install the `app` module. This repository does not rely on a committed Gradle wrapper binary. Release signing is documented in `SIGNING.md`.

## Pairing

1. Start the server: `python main.py --start`.
2. Create a Pair Code: `python main.py --pair`.
3. Use the companion pairing UI with the displayed code. The configured public endpoint is `https://auth.kasirdigital.web.id`, allowing supported off-LAN pairing without manually entering a LAN server URL.
4. The companion creates/persists its device identity and reconnects through signed challenge/response.

Pairing establishes identity and permitted capabilities; it is not blanket device permission.

## Interactive voice

Microphone capture and JARVIS audio playback run on the companion, not on the server. During an Android-originated voice turn, command origin (`origin_device_id`) and response-audio target (`active_voice_device`) are intentionally separate state even though both normally refer to this phone.

## Native capabilities

The companion advertises supported capabilities such as command submission, notifications, vibration, clipboard, URL opening, app launching, and Android Accessibility UI actions. The server must route only capabilities currently advertised by the connected companion.

Android UI capabilities include inspection, click, text entry, scrolling, and global navigation. App resolution accepts natural app names where supported by the companion/server resolver.

## Accessibility UI control

Enable JARVIS Companion explicitly in Android Accessibility Settings. The app cannot silently enable this permission. If disabled, `android.ui.*` actions fail closed.

Automation should inspect the current UI before deciding what to click/type and inspect again after important actions. A failed click should trigger recovery/inspection rather than blind repeated scrolling.

The companion does not silently add root, ADB/Shizuku, Device Owner, arbitrary shell, protected-settings access, or unrestricted filesystem access.

## Troubleshooting

- **App launch works but UI actions fail:** verify Accessibility is enabled, then retry after UI inspection.
- **Server says device offline:** confirm the companion is connected; if duplicate historical device names exist, the server should resolve the currently online record/UUID.
- **Voice has no response audio:** do not change Android audio handling solely to fix command routing. Server command-origin and active-voice state are separate and must both remain valid.

## Current MARK-LIV control model

Android is a companion endpoint for a headless MARK-LIV server. Device UI automation is application-agnostic and uses generic Accessibility capabilities with an inspect -> act -> verify loop. Application/package names are target data, not automation recipes.

Credential fields are a hard boundary: the companion must not accept automated PIN/password/passcode/credential entry. Normal non-credential UI operations remain available when Accessibility and the required Android permission are enabled.

Ending a conversation does not stop the MARK-LIV server. Cross-device generic file transfer is not yet advertised as an Android companion capability.

## Voice end and reconnect lifecycle

An intentional end-call action sets explicit local ended state before the voice WebSocket closes. Close/failure callbacks cannot auto-reconnect while that state is active. Unexpected transport loss remains recoverable. Starting a new explicit voice connection clears the state.


### Re-pair identity replacement
A fresh explicit Pair Code can replace one unambiguous offline stale identity with the same companion-reported name after reinstall. Normal reconnect does not delete trust, and ambiguous same-name devices are never removed automatically.

## File transfer
The Android companion advertises generic `file.upload` and `file.receive` capabilities. Upload sources must be a path or content URI Android permits the companion to read; private data belonging to other applications is not bypassed. On Android 10 and newer, received files are written through MediaStore to `Downloads/MARK-LIV` and verified by SHA-256 and byte size. Android versions below 10 return a clear unsupported error for shared-Downloads receive rather than claiming success without the required legacy storage permission.


### Attachment inbox
Incoming transfers appear in the companion attachment inbox, including attachments queued while this device was offline. No destination directory is selected by the sender. Open downloads a verified temporary local cache copy; Save As lets the recipient choose a local location; Share uses the native Android share sheet (desktop companions explain where the OS share-sheet integration is unavailable). The source companion can open its native file picker when the source path is omitted. Files remain on the server as single-copy objects for up to 30 days while inbox references exist, unless the user explicitly requests permanent server retention. The legacy file.receive capability remains available for compatibility but is not used by the transfer_file tool.


### Overflow companion menu and final-turn attachment picker
Android keeps the main voice surface uncluttered: Attachments and Device Control are grouped under the top-right overflow menu. Each destination opens a richer status/action dialog instead of occupying the app bar. Deferred attachment selection no longer uses transient SPEAKING/LISTENING state changes. The runtime emits `assistant.turn.complete` only after the completed Live turn has drained from the companion audio queue; Android and Desktop release a pending native file picker only on that event. Attachment lifecycle diagnostics use warning/error severity markers so detached-server `runtime/error.log` retains picker queued/selected/cancelled, transfer complete, and transfer failure checkpoints without file contents, local source paths, hashes, or transfer tokens.


### Single-request attachment transaction and companion-styled menus
A Live user turn owns at most one attachment transaction for a source/destination pair. Once native selection is queued, repeated `transfer_file` calls in the same user turn—including model-generated content URIs—reuse the existing transaction status and cannot open another picker or upload another file. The server records completion/failure/cancellation for that request so a retry receives the real outcome rather than starting over. Android companion submenus now follow the main dark/cyan visual language with circular action icons, clearer status copy, and middle-ellipsized filenames that keep the file extension visible.


### Multi-file attachment batches
A single explicit attachment request may select multiple files in one native picker. Android uses `ACTION_OPEN_DOCUMENT` with multi-selection enabled; Desktop uses its native multi-file picker. The selection is sent as one logical batch transaction, while every selected file remains an independent durable attachment in the recipient inbox and single-copy object store. Batch results report total/completed/failed counts and per-item results. Partial failure does not reopen the picker or retry the whole batch. The one-transaction-per-user-turn guard remains in force.


### Unified companion panel

The overflow menu, Received/Sent attachments, Device Control and recipient actions share one styled panel. Back navigation and a compact close icon replace stacked dialogs and large footer close buttons.

### Send files to server

A voice request to send files to the server opens the Android multi-select picker and stores the selected files permanently on the server. The Sent tab shows Stored on server; the phone does not receive its own upload as an incoming attachment.

### Received and Sent attachments

The Attachments dialog has Received and Sent views in the main companion’s dark and cyan visual style. Sent history is read-only; Open, Save As and Share are available only to recipients. Files uploaded to MARK LIV for processing appear in Sent and do not show up as incoming files on the same phone.

### Voice attachment picker

Voice requests can queue the Android native multi-select picker after the assistant finishes speaking. No chat upload is required.

### Document attachment filenames

Selected Android documents retain their displayed name and extension when uploaded into the recipient inbox.

### Attachment picker diagnostics and duplicate-name routing
Attachment picker delivery now has explicit `received` and `opened` acknowledgements, persisted by the server diagnostic logger. Android and Desktop remember whether the current assistant turn has already completed, so a picker request arriving immediately after the completion event is opened once instead of waiting forever for an event that already occurred. SPEAKING/THINKING resets that completion latch for the next response.

Device-name resolution now prefers an exact device ID. When several non-revoked records share the same display name, exactly one currently-online match may be selected; multiple online matches remain ambiguous and are never guessed. Historical trust records are not silently deleted because identical model names can represent different physical devices.

## Companion surfaces

The compact pairing screen uses the same dark card, cyan primary action, and JARVIS header as the voice screen. Its status line appears only during pairing or when input needs attention. Received and Sent attachment tabs have transparent backgrounds with a cyan underline for the selected tab; file history and recipient-only actions are unchanged.
