# Desktop companion

The Windows, Linux, and macOS companion provides voice, a PyQt control surface, local device actions, and attachments for the headless Mark server. Its interface uses the standard animated reactor core; attribution is retained in the license and source.

## Install and run

From the repository root:

```bash
python desktop-companion/install.py
python desktop-companion/companion.py
```

Desktop audio, GUI, camera, browser, and input-control dependencies belong to this environment, not the server environment.

## Pairing

1. Click **REQUEST PAIRING** with the code field empty.
2. On the server run `python main.py --pair` to review the desktop request.
3. Issue its code with `python main.py --pair --pairing-id <request-id>`.
4. Enter the eight-character code and click **FINISH PAIRING**.

Desktop and Android use the same request/claim protocol. Codes are bound to an individual signed request, not interchangeable between devices. Clear the code field and request pairing again if a request expires. Existing paired identities continue to use signed reconnects.

Desktop state is saved atomically with owner-only permissions. An unreadable, corrupt, partial, or mismatched identity stops startup instead of creating replacement keys. Restore the existing state file rather than deleting it to clear an error.

Public HTTPS verifies certificates. Private LAN transport retains its existing self-signed behavior. Pairing and connection errors are reported without replacing a trusted identity silently.

## Local execution

Device-local commands stay on this computer unless another device/server is explicitly selected. `local_runtime.py` and `runtime/` carry desktop action support; platform capabilities and permissions still apply. Credential input is protected.

Camera capture returns a verified frame from the configured/default webcam. Video playback uses optional Qt Multimedia and media-resolution dependencies on the companion. The server does not open a local media window.

The control menu includes reconnect, pairing, microphone mute, interruption, audio-device selection, attachments, and full screen. Ending a conversation leaves the server running.

## Attachments and logs

Received files use the attachment Inbox, with Open, Save As, and platform-appropriate Share behavior. Received and Sent entries also provide list removal and confirmed server-attachment deletion. Multi-file pickers use one request per batch. See [file handling](../docs/files.md).

Desktop failures are recorded in `~/.mark-companion/logs/error.log`, or `%USERPROFILE%\\.mark-companion\\logs\\error.log` on Windows. The log rotates at 2 MB with two backups; routine activity appears in the HUD. Server logs are separate.
