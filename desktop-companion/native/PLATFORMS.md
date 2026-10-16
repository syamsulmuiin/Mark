# Companion native audio builds

The WebRTC APM wrapper is **companion-side**. Mark's headless server does not need AEC3.

- Windows x64: .github/workflows/build-webrtc-aec3.yml
- Linux x64 and macOS x64/arm64: .github/workflows/build-webrtc-aec3-unix.yml
- Android: android-companion/.../audio/VoiceEchoController.kt provides Android platform AEC/NS, not WebRTC AEC3. It must be wired to the active AudioRecord session before claiming runtime integration.

Build artifacts are provisional until compilation, C ABI tests, playback-reference/capture integration and echo-reduction tests pass. Never auto-install unverified binaries.
