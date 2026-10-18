# Android companion

The native Android companion provides voice, device control, and attachments for the headless Mark server. Device-local requests default to this phone.

## Build and install

Use JDK 17 and Android SDK 35. Open this directory in Android Studio or use the Gradle version configured in [the build workflow](../.github/workflows/build-android.yml). A Gradle wrapper binary is not committed.

GitHub Actions publishes `Companion-debug` and, when signing secrets are configured, `Companion-release-signed`. Use the same release signing key for updates over an existing installation. See [signing](SIGNING.md).

## Pairing

Request pairing from the companion, review the pending request with `python main.py --pair` on the server, then issue a code using `--pair --pairing-id <request-id>`. Enter the one-time, eight-character code on the requesting phone. See the [setup guide](../docs/setup.md).

The saved Ed25519 identity supports reconnects. Normal transport failures retain pairing. Authentication failures preserve keys and pause retries; only an explicit server revocation clears the paired flag. Do not clear app data merely to recover a network connection.

## Device control

The companion advertises capabilities backed by native handlers. Accessibility automation is optional and must be enabled in Android Settings. Control follows inspect, act, and verify; ordinary Android permissions still apply. The app does not silently gain root, ADB, Device Owner, or force-stop access to arbitrary third-party apps.

Credential entry remains a user action. Browser UI work stays in the phone's browser and its existing session.

## Voice and attachments

Microphone capture and playback run on the phone. Android AEC/NS and local speech gating assist interruption handling; behavior still depends on hardware and environment.

The companion menu contains Attachments and Device Control. Received entries support Open, Save As, and Share. Received and Sent entries support Remove from my list and confirmed Delete server attachment. Normal delivery does not force a Downloads destination. Native source selection supports multiple files.

See [files and attachments](../docs/files.md) for retention, verification, and deletion scope. Companion source changes require a new APK; server-only changes do not.
