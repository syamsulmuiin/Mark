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
