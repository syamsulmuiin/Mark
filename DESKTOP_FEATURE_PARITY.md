# Desktop feature parity review

This review compares the original `FatihMakes/Mark-LV` desktop UI and actions with the MARK LIV headless server and native desktop companion. The reference application ran the assistant and its GUI in one process. Server-owned controls now require a server interface, while hardware and desktop actions remain on the companion.

| Original function | Current placement | Review result |
|---|---|---|
| Text command and interactive voice | Companion, forwarded to headless server | Preserved; requires a connected device WebSocket. |
| App, browser, file, screen and computer actions | Companion `legacy.action` bridge | Preserved in local runtime; actions are routed to the originating desktop. |
| Visual analysis of the current screen | Companion `screen.capture` and server Live vision | Restored a real screen frame from the origin desktop, validated and attached to the active model exchange. |
| YouTube/video playback | Companion local runtime | `youtube_video` remains browser/transcript oriented; `video_player` now plays local files, direct media URLs, and resolved YouTube streams in a companion-local Qt Multimedia window, muted by default. |
| Local microphone/speaker selection | Companion menu | Restored with the active stream restarted after a device change. |
| Mute and interrupt | Companion menu | Restored; mute gates outbound audio, interrupt uses the existing server message. |
| Full screen and attachments | Companion menu | Available from one grouped control menu. |
| Cloudflare remote link | Headless server | HTTP 502 occurs before WebSocket authentication. Desktop now attempts signed LAN discovery for an already paired device; new Pair Codes can also fall back to LAN. This does not repair a down server or Cloudflare configuration for off-LAN devices. |
| Memory, plugins, remote access, assistant customization | Headless server | These are server-owned controls. The previous in-process Qt dialogs cannot safely be copied to the companion as local configuration; a separate authenticated server settings protocol would be needed. |
| Wake word and startup briefing | Companion/server policy | Server microphone and automatic briefing were intentionally disabled in the headless design. Do not silently restore them as server audio jobs. |
| Holographic face and HUD style switch | Retired | The standard reactor remains, as requested. |
| In-HUD video playback | Desktop Companion Qt Multimedia | Added a companion-local `video_player` action for local files, direct media URLs, YouTube links/searches, stop, mute, and unmute. Playback stays on the paired desktop; the headless server does not install or execute browser/media UI dependencies. |

## HTTP 502 from the attached desktop log

Two WebSocket handshakes returned HTTP 502 from Cloudflare. The request did not reach the signed device challenge, so this log does not identify a failure in voice, attachments, or a local action. Verify that the headless server is running and that the Cloudflare Named Tunnel public hostname forwards HTTP to the configured local dashboard port. Signed LAN discovery offers a fallback only when the desktop and server can reach each other on the same network.
