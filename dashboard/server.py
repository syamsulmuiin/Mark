"""
dashboard/server.py — JARVIS Local HTTP Dashboard

Plain HTTP on configured HTTP port (no SSL warnings, no firewall issues).
Security at the application layer: AES-256-CBC with session-key-derived key.
CryptoJS is auto-downloaded once and served locally — no CDN needed after that.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import asyncio
import base64
import hashlib
import re
import secrets
import socket
import string
import time
import json
import os
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
from core.device_mesh import DeviceMesh
from core.cloudflare_tunnel import NamedTunnel, enabled as cloudflare_enabled, public_url as cloudflare_public_url
from core.network_config import DASHBOARD_PORT, LAN_HTTPS_PORT, DISCOVERY_PORT
STATIC_DIR  = Path(__file__).parent / "static"
PORT        = DASHBOARD_PORT
DISCOVERY_MAGIC = "MARKLIV_DISCOVER_V1"
MAX_UPLOAD_MB = 500


def _make_storage_dirs() -> dict[str, Path]:
    """Create the project-local server file repository."""
    root = BASE_DIR / "storage"
    paths = {
        "root": root,
        "uploads": root / "uploads",
        "share": root / "share",
        "downloads": root / "downloads",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


STORAGE_DIRS = _make_storage_dirs()
UPLOADS_DIR = STORAGE_DIRS["uploads"]
SHARE_DIR = STORAGE_DIRS["share"]
DOWNLOADS_DIR = STORAGE_DIRS["downloads"]

def _get_gemini_key() -> str | None:
    try:
        import json as _json
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return _json.load(f).get("gemini_api_key")
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# ── AES-256-CBC ───────────────────────────────────────────────────────────────
_AES_SALT = b'JARVIS-DASHBOARD-v1'


def _derive_key(session_key: str) -> bytes:
    """SHA-256(sessionKey‖salt) → 32-byte AES-256 key (microseconds, no PBKDF2 needed)."""
    return hashlib.sha256(session_key.encode('utf-8') + _AES_SALT).digest()


def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(IV[16] ‖ ciphertext) with AES-256-CBC + PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw      = base64.b64decode(enc_b64)
    iv, ct   = raw[:16], raw[16:]
    dec      = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


# ── CryptoJS (auto-download once, served locally) ─────────────────────────────
_CRYPTOJS_CDN  = ("https://cdnjs.cloudflare.com/ajax/libs/"
                  "crypto-js/4.2.0/crypto-js.min.js")
_CRYPTOJS_FILE = STATIC_DIR / "crypto-js.min.js"


def _ensure_network_access(port: int) -> None:
    """Cross-platform, best-effort: open port in the OS firewall for LAN access.

    Runs in a background thread — never blocks uvicorn startup.

    Windows : writes a .bat file, runs it elevated via Windows ShellExecuteW
              (native UAC dialog, guaranteed to appear). One-time setup.
    macOS   : osascript admin dialog if the Application Firewall is on.
    Linux   : pkexec GUI → sudo -n → prints manual command as fallback.
    """
    import sys, subprocess, os, tempfile, threading

    # ── Windows ──────────────────────────────────────────────────────────────
    if sys.platform == "win32":
        import ctypes, time

        port_rule = f"JARVIS Dashboard Port {port}"
        prog_rule  = "JARVIS Dashboard Python"
        py_exe     = sys.executable

        def _netsh_rule_exists(name: str) -> bool:
            try:
                r = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                    capture_output=True, text=True, timeout=5,
                )
                return r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                return False

        def _network_is_public() -> bool:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-NetConnectionProfile | "
                     "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                     "Measure-Object).Count"],
                    capture_output=True, text=True, timeout=6,
                )
                return r.stdout.strip() not in ("", "0")
            except Exception:
                return False

        need_port    = not _netsh_rule_exists(port_rule)
        need_prog    = not _netsh_rule_exists(prog_rule)
        need_private = _network_is_public()

        if not need_port and not need_prog and not need_private:
            return  # already fully configured

        # Build a .bat file — netsh + powershell, runs fast when elevated
        bat_lines = ["@echo off"]
        if need_private:
            bat_lines.append(
                'powershell -NoProfile -NonInteractive -Command "'
                'Get-NetConnectionProfile | '
                "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                'Set-NetConnectionProfile -NetworkCategory Private"'
            )
        if need_port:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{port_rule}" protocol=TCP dir=in '
                f'localport={port} action=allow'
            )
        if need_prog:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{prog_rule}" dir=in action=allow '
                f'program="{py_exe}" enable=yes'
            )

        bat_body = "\r\n".join(bat_lines) + "\r\n"
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="jarvis_fw_")
        try:
            os.write(fd, bat_body.encode("mbcs"))   # Windows cmd.exe expects ANSI
            os.close(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return

        # ── Try running directly (succeeds when already admin) ────────────────
        try:
            r = subprocess.run(
                [bat_path], capture_output=True, timeout=8, shell=True
            )
            if r.returncode == 0:
                print(f"[Dashboard] Firewall configured for port {port}.")
                try:
                    os.unlink(bat_path)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # ── ShellExecuteW: native UAC elevation (most reliable on Windows) ────
        # ShellExecuteW with verb "runas" always shows the UAC dialog regardless
        # of UAC level settings. Non-blocking — uvicorn is already running.
        print("[Dashboard] One-time network setup required.")
        print("[Dashboard] >>> A Windows security dialog will appear — click 'Yes' <<<")
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,       # hwnd  (no parent window)
                "runas",    # verb  (request elevation)
                bat_path,   # file  (our .bat)
                None,       # params
                None,       # working dir
                0,          # SW_HIDE (run without a visible cmd window)
            )
            if int(ret) > 32:
                # ShellExecuteW returns immediately; bat finishes in ~1 second.
                # Sleep briefly so the rules are in place before the first retry.
                time.sleep(2)
                print(f"[Dashboard] Network setup complete — port {port} is open.")
                print("[Dashboard] Refresh your phone browser to connect.")
            else:
                print("[Dashboard] Setup was not allowed.")
                print("[Dashboard] Phone connections may fail until JARVIS is run as Administrator.")
        except Exception as e:
            print(f"[Dashboard] Firewall setup error: {e}")
        finally:
            # Cleanup after the bat has had time to run
            def _cleanup(path: str) -> None:
                time.sleep(5)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(bat_path,), daemon=True).start()
        return

    # ── macOS ─────────────────────────────────────────────────────────────────
    if sys.platform == "darwin":
        fw_ctl = "/usr/libexec/ApplicationFirewall/socketfilterfw"
        try:
            r = subprocess.run(
                [fw_ctl, "--getglobalstate"], capture_output=True, text=True, timeout=5,
            )
            if "disabled" in r.stdout.lower():
                return  # firewall off — nothing to do

            py = sys.executable
            listed = subprocess.run(
                [fw_ctl, "--listapps"], capture_output=True, text=True, timeout=5,
            )
            if py in listed.stdout:
                return  # already allowed

            print("[Dashboard] One-time network setup — enter your password in the macOS dialog.")
            subprocess.run(
                ["osascript", "-e",
                 f'do shell script "{fw_ctl} --add {py} && {fw_ctl} --unblockapp {py}"'
                 f' with administrator privileges'],
                timeout=60,
            )
        except Exception:
            pass  # macOS firewall is off by default — silent failure is fine
        return

    # ── Linux ─────────────────────────────────────────────────────────────────
    def _privileged(cmd: list[str]) -> bool:
        for prefix in (["pkexec"], ["sudo", "-n"]):
            try:
                r = subprocess.run(prefix + cmd, capture_output=True, timeout=30)
                if r.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    try:  # ufw
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
        if "active" in r.stdout.lower():
            if _privileged(["ufw", "allow", f"{port}/tcp"]):
                print(f"[Dashboard] ufw: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo ufw allow {port}/tcp")
            return
    except FileNotFoundError:
        pass

    try:  # firewalld
        r = subprocess.run(
            ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5,
        )
        if "running" in r.stdout.lower():
            ok = (_privileged(["firewall-cmd", "--add-port", f"{port}/tcp", "--permanent"])
                  and _privileged(["firewall-cmd", "--reload"]))
            if ok:
                print(f"[Dashboard] firewalld: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload")
            return
    except FileNotFoundError:
        pass

    try:  # iptables (not persistent but works until reboot)
        r = subprocess.run(["iptables", "-L", "INPUT", "-n"], capture_output=True, timeout=5)
        if r.returncode == 0:
            if _privileged(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]):
                print(f"[Dashboard] iptables: port {port} opened.")
            else:
                print(f"[Dashboard] Run manually:  sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT")
    except FileNotFoundError:
        pass  # no iptables means firewall is probably off — nothing to do


def _ensure_crypto_js() -> None:
    if _CRYPTOJS_FILE.exists():
        return
    try:
        import urllib.request
        print("[Dashboard] Downloading CryptoJS (one-time setup)…")
        urllib.request.urlretrieve(_CRYPTOJS_CDN, str(_CRYPTOJS_FILE))
        print("[Dashboard] CryptoJS cached — will serve locally from now on.")
    except Exception as e:
        print(f"[Dashboard] CryptoJS download failed: {e}")
        print(f"[Dashboard] Encryption will fall back to CDN load on client.")


# Native-companion-only server: no browser dashboard assets are downloaded.


# ── helpers ───────────────────────────────────────────────────────────────────

def _local_ip() -> str:
    """Return the best LAN-facing IPv4 address, no internet required."""
    # Method 1: route trick (fast, works when internet is available)
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    # Method 2: hostname resolution (works offline on most systems)
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Method 3: enumerate all interfaces (fully offline, no external deps)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def _ensure_certs() -> bool:
    """
    Make sure config/certs holds a TLS key pair, generating a self-signed one the
    first time the dashboard runs.

    The pair is deliberately NOT shipped in the repository. A private key that
    every user downloads is the same as having no private key at all: anyone can
    present a certificate that matches it. Generating locally gives each install
    its own key, costs about a second, and happens exactly once.

    Returns True when a usable pair exists afterwards; False leaves the caller on
    plain HTTP, which still works — the QR code simply encodes http:// instead.
    """
    certs = BASE_DIR / "config" / "certs"
    key_p = certs / "jarvis.key"
    crt_p = certs / "jarvis.crt"
    if key_p.exists() and crt_p.exists():
        return True

    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("[Dashboard] cryptography not installed — serving over plain HTTP.")
        print("[Dashboard] For HTTPS run:  pip install cryptography")
        return False

    try:
        certs.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        who = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "JARVIS Dashboard"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JARVIS"),
        ])

        # The SAN has to cover every address the phone might use: the LAN IP the
        # QR code encodes, plus localhost when testing on the machine itself.
        alt = [x509.DNSName("localhost"),
               x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        try:
            lan = _local_ip()
            if not lan.startswith("127."):
                alt.append(x509.IPAddress(ipaddress.IPv4Address(lan)))
        except Exception:
            pass          # no LAN address resolvable — localhost entries still work

        # Timezone-aware UTC: datetime.utcnow() is deprecated from Python 3.12 on,
        # and the builder normalises aware values to UTC itself.
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(who)
            .issuer_name(who)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )

        key_p.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        crt_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        try:
            import os as _os
            _os.chmod(key_p, 0o600)   # best effort — largely a no-op on Windows
        except Exception:
            pass

        print(f"[Dashboard] Generated a self-signed certificate for this machine: {certs}")
        return True
    except Exception as e:
        print(f"[Dashboard] Certificate generation failed ({e}) — serving over plain HTTP.")
        return False


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


# ── DashboardServer ───────────────────────────────────────────────────────────

class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        self._tokens: set[str]            = set()
        self._token_keys: dict[str, str]  = {}   # auth_token → session_key
        self._aes_cache:  dict[str, bytes]= {}   # session_key → AES bytes
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._interrupt_callback          = None
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = {}  # legacy browser sessions
        self._mesh                         = DeviceMesh(BASE_DIR)
        self._tunnel                       = NamedTunnel(f"http://127.0.0.1:{PORT}")
        self._public_url                   = ""
        self._device_sockets: dict[str, WebSocket] = {}
        self._device_pending_calls: dict[str, asyncio.Future] = {}
        self._active_voice_device: str | None = None
        # Stable origin for device-local routing. Keep separate from the voice
        # transport target so tool routing can never steal or clear audio state.
        self._origin_device_id: str | None = None
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._uploads_dir                 = UPLOADS_DIR
        self.app                          = self._build_app()

    # ── one-time key management ───────────────────────────────────────────

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        return key

    def new_pairing_offer(self, expiry_secs: int = 600) -> dict:
        return self._mesh.create_pairing_offer(ttl=expiry_secs)

    def get_pairing_url(self, offer: dict) -> str:
        # Carry the JARVIS public identity in the QR. Native companions use this
        # as the out-of-band trust anchor when the LAN dashboard uses a locally
        # generated/self-signed TLS certificate.
        from urllib.parse import quote
        base = self.get_remote_url()
        return (f"{base}/pair?code={quote(offer['code'])}"
                f"&server_id={quote(self._mesh.device_id)}"
                f"&server_key={quote(self._mesh.public_key)}")

    @staticmethod
    def _ssl_enabled() -> bool:
        certs = BASE_DIR / "config" / "certs"
        return (certs / "jarvis.key").exists() and (certs / "jarvis.crt").exists()

    def get_url(self) -> str:
        # The configured dashboard port is intentionally plain HTTP. Cloudflare terminates public
        # TLS and forwards to http://the configured local HTTP endpoint. Keeping the origin HTTP
        # avoids a protocol mismatch/502 when the tunnel Public Hostname is
        # configured with service HTTP, as intended by setup.
        return f"http://{self._ip}:{PORT}"

    def get_remote_url(self) -> str:
        """Stable public endpoint when Cloudflare remote access is configured."""
        if cloudflare_enabled():
            return self._public_url or cloudflare_public_url()
        return self.get_url()

    async def _start_remote_tunnel(self) -> None:
        if not cloudflare_enabled():
            return
        try:
            self._public_url = await asyncio.to_thread(self._tunnel.start)
            print(f"[Dashboard] Cloudflare remote access: {self._public_url}")
        except Exception as e:
            self._public_url = ""
            print(f"[Dashboard] Cloudflare remote access unavailable: {e}")

    def get_manual_url(self) -> str:
        """URL for manual browser entry. When HTTPS active, points to alias port (also HTTPS)."""
        if self._ssl_enabled():
            return f"{self._ip}:{LAN_HTTPS_PORT}"
        return f"{self._ip}:{PORT}"

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    def set_interrupt_callback(self, fn) -> None:
        self._interrupt_callback = fn

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead
        # Trusted companion devices share the same live conversation surface as
        # the browser dashboard: state and transcript are pushed over their
        # already-authenticated device socket. Binary frames remain audio only.
        dead_devices = []
        for device_id, ws in list(self._device_sockets.items()):
            try:
                await ws.send_json(msg)
            except Exception:
                dead_devices.append(device_id)
        for device_id in dead_devices:
            self._device_sockets.pop(device_id, None)

    async def send_device_audio(self, pcm: bytes) -> None:
        """Send voice only to the companion that owns the current interaction."""
        # Voice output belongs to the companion that owns the live interaction.
        # If the transport target was lost during a tool/reconnect boundary, the
        # stable turn origin is the only safe fallback; never play on the server.
        device_id = self._active_voice_device
        if not device_id or device_id not in self._device_sockets:
            origin = self._origin_device_id
            if origin and origin in self._device_sockets:
                device_id = origin
                self._active_voice_device = origin
            else:
                return
        ws = self._device_sockets.get(device_id)
        if ws is None:
            return
        try:
            await ws.send_bytes(pcm)
        except Exception:
            self._device_sockets.pop(device_id, None)
            if self._active_voice_device == device_id:
                self._active_voice_device = None

    @property
    def active_voice_device(self) -> str | None:
        """Companion currently receiving interactive voice audio."""
        return self._active_voice_device

    @property
    def origin_device_id(self) -> str | None:
        """Stable companion origin for the current interaction/tool routing."""
        return self._origin_device_id

    async def call_device(self, device_id: str, capability: str, args: dict | None = None, timeout: float = 30.0):
        """Invoke an explicitly permitted capability on a connected paired node."""
        if not self._mesh.authorized(device_id, capability):
            raise PermissionError(f"{device_id} is not allowed to use {capability}")
        ws = self._device_sockets.get(device_id)
        if ws is None: raise ConnectionError("device is offline")
        call_id = secrets.token_urlsafe(12)
        fut = asyncio.get_running_loop().create_future()
        self._device_pending_calls[call_id] = fut
        try:
            await ws.send_json({"type":"capability.call", "call_id":call_id, "capability":capability, "args":args or {}})
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._device_pending_calls.pop(call_id, None)

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        # Server-only architecture: browsers are not a control surface anymore.
        # Only native-companion pairing endpoints remain exposed over HTTP; the
        # authenticated device mesh uses /ws/device below.
        @app.middleware("http")
        async def native_companions_only(req: Request, call_next):
            path = req.url.path
            allowed = (path.startswith("/api/pairing/offer/") or path == "/api/pairing/accept" or path in ("/api/local/pairing/new", "/api/local/health", "/api/upload", "/api/files") or path.startswith("/uploads/"))
            if not allowed:
                return JSONResponse({"error": "Install a MARK LIV companion client to access this server."}, status_code=404)
            return await call_next(req)

        def _auth(req: Request) -> bool:
            tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return bool(tok) and tok in self._tokens

        # serve CryptoJS from local cache, fallback to CDN redirect
        @app.get("/static/crypto.js")
        async def serve_crypto():
            if _CRYPTOJS_FILE.exists():
                return FileResponse(str(_CRYPTOJS_FILE),
                                    media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(_CRYPTOJS_CDN)

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(self._login_html)

        @app.get("/pair", response_class=HTMLResponse)
        async def pair_page():
            return HTMLResponse(self._pair_html)

        @app.get("/api/device-known/{device_id}")
        async def device_known(device_id: str):
            rec = self._mesh.get(device_id)
            return JSONResponse({"known": bool(rec and not rec.get("revoked"))})

        @app.get("/api/pairing/offer/{code}")
        async def pairing_offer_public(code: str):
            offer = self._mesh.pending_offer(code)
            if not offer:
                return JSONResponse({"error": "Pairing code invalid or expired"}, status_code=404)
            return JSONResponse(offer)

        @app.get("/api/local/health")
        async def local_health(req: Request):
            host = req.client.host if req.client else ""
            if host not in ("127.0.0.1", "::1") or req.headers.get("x-jarvis-local") != "1":
                return JSONResponse({"error": "local access only"}, status_code=403)
            return JSONResponse({"service": "MARK-LIV", "status": "ready", "pid": os.getpid()})

        @app.post("/api/local/pairing/new")
        async def local_pairing_new(req: Request):
            host = req.client.host if req.client else ""
            if host not in ("127.0.0.1", "::1") or req.headers.get("x-jarvis-local") != "1":
                return JSONResponse({"error": "local access only"}, status_code=403)
            offer = self.new_pairing_offer()
            return JSONResponse({"code": offer["code"], "expires_at": offer["expires_at"], "url": self.get_pairing_url(offer)})

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            body    = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now     = time.time()
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                del self._pending_keys[entered]          # one-time use
                tok = secrets.token_urlsafe(32)
                self._tokens.add(tok)
                self._token_keys[tok] = entered
                self._aes_key(entered)                   # pre-derive & cache
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                # Bearer token in response body — no cookies needed (works on any browser/HTTP)
                return JSONResponse({"ok": True, "token": tok})
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in JARVIS to get a new QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}

            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('jarvis_token','{tok}');
  sessionStorage.setItem('jarvis_key','{key}');
  localStorage.setItem('jarvis_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to JARVIS…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens.add(tok)
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            count = len(self._device_sessions)
            self._device_sessions.clear()
            return JSONResponse({"ok": True, "revoked": count})

        # ── Trusted device mesh ─────────────────────────────────────────────
        @app.get("/api/devices")
        async def list_paired_devices(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return JSONResponse({"local": self._mesh.public_identity(), "devices": self._mesh.list_devices()})

        @app.post("/api/pairing/offer")
        async def pairing_offer(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return JSONResponse(self._mesh.create_pairing_offer())

        @app.post("/api/pairing/accept")
        async def pairing_accept(req: Request):
            try:
                body = await req.json()
                rec = self._mesh.accept_pairing(body.get("code", ""), body.get("peer") or {},
                                                body.get("signature", ""), body.get("capabilities"))
                return JSONResponse({"ok": True, "local": self._mesh.public_identity(), "device": {k:v for k,v in rec.items() if k != "public_key"}})
            except Exception as exc:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

        @app.post("/api/devices/{device_id}/revoke")
        async def revoke_paired_device(device_id: str, req: Request):
            if not _auth(req): return JSONResponse({"error": "Unauthorized"}, status_code=401)
            ws = self._device_sockets.pop(device_id, None)
            if ws:
                try: await ws.close(code=4003)
                except Exception: pass
            return JSONResponse({"ok": self._mesh.revoke(device_id)})

        @app.websocket("/ws/device")
        async def device_mesh_ws(websocket: WebSocket, device_id: str = ""):
            rec = self._mesh.get(device_id)
            if not rec or rec.get("revoked"):
                await websocket.close(code=4001); return
            await websocket.accept()
            challenge = secrets.token_urlsafe(32)
            server_proof = self._mesh.sign((device_id + ":" + challenge).encode())
            await websocket.send_json({"type": "challenge", "challenge": challenge,
                                       "local": self._mesh.public_identity(),
                                       "server_signature": server_proof})
            try:
                proof = await asyncio.wait_for(websocket.receive_json(), timeout=15)
                if proof.get("type") != "proof" or not self._mesh.verify(rec["public_key"], challenge.encode(), proof.get("signature", "")):
                    await websocket.close(code=4003); return
                # The signed proof authenticates this peer. Refresh its advertised
                # execution capabilities on every connection so devices paired by an
                # older build do not remain permanently stuck with stale permissions.
                live_caps = proof.get("capabilities")
                if isinstance(live_caps, list) and live_caps:
                    rec = self._mesh.set_capabilities(device_id, [str(c) for c in live_caps if str(c).strip()])
                self._device_sockets[device_id] = websocket
                self._mesh.touch(device_id)
                await websocket.send_json({"type": "ready", "capabilities": rec.get("capabilities", [])})
                while True:
                    packet = await websocket.receive()
                    if packet.get("type") == "websocket.disconnect":
                        break
                    audio = packet.get("bytes")
                    if audio is not None:
                        self._origin_device_id = device_id
                        self._active_voice_device = device_id
                        try:
                            self._phone_audio_queue.put_nowait({"data": audio, "mime_type": "audio/pcm;rate=16000"})
                        except asyncio.QueueFull:
                            pass
                        continue
                    raw = packet.get("text")
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    if msg.get("type") == "jarvis.command":
                        if not self._mesh.authorized(device_id, "jarvis.command"):
                            await websocket.send_json({"type":"error","error":"capability denied"}); continue
                        text = str(msg.get("text") or "").strip()
                        if text:
                            self._origin_device_id = device_id
                            self._active_voice_device = device_id
                            await self._command_queue.put(text)
                            if self._wake_callback: self._wake_callback()
                    elif msg.get("type") == "jarvis.interrupt":
                        # Same interruption path as the desktop keyboard/UI: stop
                        # the current answer immediately and reopen listening.
                        if self._interrupt_callback:
                            self._interrupt_callback()
                    elif msg.get("type") == "capability.result":
                        call_id = str(msg.get("call_id") or "")
                        fut = self._device_pending_calls.pop(call_id, None)
                        if fut and not fut.done(): fut.set_result(msg)
            except (WebSocketDisconnect, asyncio.TimeoutError):
                pass
            finally:
                if self._device_sockets.get(device_id) is websocket:
                    self._device_sockets.pop(device_id, None)
                if self._active_voice_device == device_id:
                    self._active_voice_device = None
                # Keep origin affinity across transient disconnects. The same paired
                # device may reconnect while its Live turn/tool call is still active.
                # call_device() still requires an actually connected socket, so retaining
                # this id cannot execute against an offline device or another companion.

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        # ── Phone mic real-time audio → Gemini Live ──────────────────────────

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        # ── File sharing ──────────────────────────────────────────────────────

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name                          # strip path components
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                dest = self._uploads_dir / safe
                stem, suffix = Path(safe).stem, Path(safe).suffix
                counter = 1
                while dest.exists():
                    dest = self._uploads_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": str(exc)}, status_code=500)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            # Auth via query param — browser <a download> can't send custom headers
            tok = token.strip()
            if not tok or tok not in self._tokens:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = re.sub(r'[/\\]', '', filename)
            path = self._uploads_dir / safe
            if not path.exists() or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=safe)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            self._clients.add(websocket)
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        return app

    # ── serve ─────────────────────────────────────────────────────────────

    async def _serve_alias(self) -> None:
        """Second HTTPS server on PORT+1 sharing the same app and in-memory state.
        Chrome HTTPS-upgrades any bare IP:PORT the user types, so this port also needs TLS.
        User types IP:<LAN_HTTPS_PORT> → Chrome tries https → self-signed cert warning → accept once → done."""
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, LAN_HTTPS_PORT)
        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=LAN_HTTPS_PORT, log_level="warning",
            ssl_keyfile=str(ssl_key), ssl_certfile=str(ssl_cert),
        )
        print(f"[Dashboard] Manual entry:  {self._ip}:{LAN_HTTPS_PORT}  (type in browser, accept cert once)")
        await uvicorn.Server(cfg).serve()

    def _serve_pairing_discovery(self) -> None:
        """LAN discovery for native companions. A valid Pair Code is the lookup key."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", DISCOVERY_PORT))
            while True:
                data, addr = sock.recvfrom(2048)
                try:
                    req = json.loads(data.decode("utf-8"))
                    if req.get("magic") != DISCOVERY_MAGIC:
                        continue
                    code = str(req.get("code") or "").upper()
                    offer = self._mesh.pending_offer(code)
                    if not offer:
                        continue
                    reply = {"magic": DISCOVERY_MAGIC, "code": code, "server": self.get_remote_url(),
                             "device_id": self._mesh.device_id, "public_key": self._mesh.public_key}
                    sock.sendto(json.dumps(reply).encode("utf-8"), addr)
                except Exception:
                    continue
        finally:
            sock.close()

    def assert_port_available(self) -> None:
        """Fail before any companion/tunnel task is started when the HTTP port is owned.

        A second MARK-LIV worker used to launch Uvicorn in a detached asyncio task.
        Uvicorn then raised SystemExit(1) on EADDRINUSE, which cancelled the active
        Gemini Live session as collateral damage.  Check synchronously so the duplicate
        worker exits cleanly without touching the already-running server.
        """
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("0.0.0.0", PORT))
        except OSError as exc:
            if getattr(exc, "errno", None) in (48, 98, 10048):
                raise RuntimeError(
                    f"MARK LIV HTTP port {PORT} is already in use. "
                    "Another MARK LIV server may already be running; stop that instance before starting a second one."
                ) from exc
            raise
        finally:
            probe.close()

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]' cryptography")
            return

        # Pair-code LAN discovery is headless and exposes no interactive server UI.
        asyncio.get_event_loop().run_in_executor(None, self._serve_pairing_discovery)

        # Start the optional outbound-only Cloudflare tunnel. It exposes the same
        # dashboard/device WebSocket; JARVIS pairing still authenticates devices.
        asyncio.create_task(self._start_remote_tunnel())

        # Firewall setup runs in a thread — uvicorn starts immediately,
        # no waiting for UAC dialogs or subprocess timeouts.
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT)

        # Cloudflare Public Hostname is configured as HTTP -> the configured local HTTP endpoint.
        # Therefore configured HTTP port MUST stay HTTP. Public traffic is still HTTPS
        # because TLS terminates at Cloudflare. Keep the self-signed HTTPS LAN
        # alias on the configured LAN HTTPS port for clients that explicitly want local TLS.
        _ensure_certs()
        if self._ssl_enabled():
            asyncio.create_task(self._serve_alias())

        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT, log_level="warning"
        )

        print(f"[Dashboard] http://{self._ip}:{PORT}")
        print("[Dashboard] Press 'Remote Control' in JARVIS UI to get the QR code.")
        await uvicorn.Server(cfg).serve()
