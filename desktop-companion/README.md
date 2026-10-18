# Desktop companion

The Windows, Linux, and macOS companion provides voice, a PyQt control surface, local device actions, and attachments for the headless Mark server. Its interface uses the standard animated reactor core; attribution is retained in the license and source.

## Install and run

From the repository root:

```bash
python desktop-companion/install.py
python desktop-companion/companion.py
```

Desktop audio, GUI, camera, browser, and input-control dependencies belong to this environment, not the server environment.

## Pairing compatibility

The desktop client currently expects a six-character Pair Code and uses `/api/pairing/offer` and `/api/pairing/accept`. Android uses a separate eight-character request/claim flow. Do not assume these codes or setup steps are interchangeable.

The current server CLI reviews request/claim pairing requests; it does not issue a legacy desktop offer. New desktop pairing through that CLI remains a compatibility limitation. Existing paired desktop identities use signed reconnects. Check client/server protocol compatibility before replacing a working installation.

Public HTTPS verifies certificates. Private LAN transport retains its existing self-signed behavior. Pairing and connection errors are reported without replacing a trusted identity silently.

## Local execution

Device-local commands stay on this computer unless another device/server is explicitly selected. `local_runtime.py` and `runtime/` carry desktop action support; platform capabilities and permissions still apply. Credential input is protected.

Camera capture returns a verified frame from the configured/default webcam. Video playback uses optional Qt Multimedia and media-resolution dependencies on the companion. The server does not open a local media window.

The control menu includes reconnect, pairing, microphone mute, interruption, audio-device selection, attachments, and full screen. Ending a conversation leaves the server running.

## Attachments and logs

Received files use the attachment Inbox, with Open, Save As, and platform-appropriate Share behavior. Received and Sent entries also provide list removal and confirmed server-attachment deletion. Multi-file pickers use one request per batch. See [file handling](../docs/files.md).

Desktop failures are recorded in `~/.mark-companion/logs/error.log`, or `%USERPROFILE%\\.mark-companion\\logs\\error.log` on Windows. The log rotates at 2 MB with two backups; routine activity appears in the HUD. Server logs are separate.
