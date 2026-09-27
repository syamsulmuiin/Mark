# MARK-LIV Desktop Companion

Native companion runtime for Windows, Linux, and macOS. It is the desktop user-facing control/execution surface for the headless MARK-LIV server and carries the established local action runtime so device-local commands execute on this computer.

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
