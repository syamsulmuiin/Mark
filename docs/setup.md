# Installation and pairing

## Server environment

Run `python setup.py` from the repository root. The supported server environment requires Python 3.11 or newer; CI covers 3.11–3.13. Linux setup creates a project-local virtual environment when needed. Use that environment's interpreter for installation, maintenance, and startup.

The server does not need a display, local microphone, speaker, or desktop automation stack. Companion dependencies are installed separately. Setup also installs Playwright Chromium on supported x86_64/ARM64 hosts. `SKIP_BROWSER_INSTALL=1` skips that browser installation; server browser automation then requires a compatible runtime before use.

Configure Text first, then Live. Both selections are saved only after the complete setup flow succeeds. See [provider configuration](llm-providers.md).

## Network configuration

Edit `config/network.json` for server endpoints and ports. Resolution follows environment overrides, then JSON configuration, then built-in defaults. The desktop standalone runtime carries a corresponding network configuration; Android embeds its public URL at build time.

Use a trusted public TLS endpoint for remote access. A tunnel provides transport, not device authorization. The local HTTP API must be healthy for pairing and file transfer.

## Android pairing

1. Start the server with `python main.py --start`.
2. Request pairing from the Android companion.
3. Run `python main.py --pair` on the server to review pending requests.
4. Issue a code with `python main.py --pair --pairing-id <request-id>`.
5. Enter the one-time, eight-character code on the requesting phone.

The code is bound to that device's signed pairing request and expires with it. Normal reconnects use persistent Ed25519 identity, not a fresh code.

Desktop uses the same eight-character request/claim protocol. Click REQUEST PAIRING first, issue the code for that desktop request on the server, then enter it and finish pairing. See the [desktop guide](../desktop-companion/README.md). Android upgrades with an older pending request must request pairing again; an established paired identity does not need to be reset.

## Persistent state

Preserve `config/`, `devices/identity.json`, `devices/trusted_devices.json`, required memory files, and `storage/` across upgrades. Do not commit credentials or generated state. Corrupt identity/trust files stop startup instead of silently creating replacement identities.

Install Android updates over the existing app using the same signing identity. Uninstalling or clearing app data can remove the companion key and require pairing again.

## Local operator authentication

Local health and pairing administration require both loopback access and the owner-readable credential in `devices/local_api.token`. The server creates it at startup and the local CLI reads it automatically. A proxy's loopback connection or the fixed `X-Jarvis-Local` header alone grants no operator authority. Keep this file private and outside Git; do not send it to companions. Restart the server after updating so the new endpoint and CLI contracts are active together.
