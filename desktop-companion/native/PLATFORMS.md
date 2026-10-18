# Companion native audio builds

The WebRTC APM wrapper is **companion-side**. Mark's headless server does not need AEC3.

- Windows x64: .github/workflows/build-webrtc-aec3.yml
- Linux x64 and macOS x64/arm64: .github/workflows/build-webrtc-aec3-unix.yml
- Android: android-companion/.../audio/VoiceEchoController.kt provides Android platform AEC/NS, not WebRTC AEC3. MainActivity attaches it to each active AudioRecord session and releases it on stop. Actual echo suppression depends on device support and still requires device testing.

Build artifacts are provisional until compilation, C ABI tests, playback-reference/capture integration and echo-reduction tests pass. Never auto-install unverified binaries.
