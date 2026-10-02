"""Cloudflare Named Tunnel transport for JARVIS device pairing.

Cloudflare is transport only. JARVIS device identity, mutual proof, capability
permissions and revocation remain enforced by core.device_mesh.
"""
from __future__ import annotations
import json, os, platform, shutil, subprocess, threading, urllib.request, tarfile
from pathlib import Path
from core.network_config import PUBLIC_HOSTNAME, LOCAL_BASE_URL

BASE_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BASE_DIR / "runtime" / "cloudflared"
STATE_FILE = BASE_DIR / "config" / "remote_access.json"
DEFAULT_HOSTNAME = PUBLIC_HOSTNAME
DEFAULT_LOCAL_URL = LOCAL_BASE_URL
TOKEN_ENV = "ASSISTANT_CLOUDFLARE_TUNNEL_TOKEN"


def _exe(): return BIN_DIR / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")
def installed(): return _exe().exists() or shutil.which("cloudflared") is not None
def executable(): return str(_exe() if _exe().exists() else shutil.which("cloudflared") or _exe())
def _asset():
    s=platform.system(); m=platform.machine().lower()
    if s=="Windows": return "cloudflared-windows-amd64.exe" if "64" in m or "amd64" in m or "x86_64" in m else "cloudflared-windows-386.exe"
    if s=="Darwin": return "cloudflared-darwin-arm64.tgz" if "arm" in m else "cloudflared-darwin-amd64.tgz"
    return "cloudflared-linux-arm64" if ("arm64" in m or "aarch64" in m) else "cloudflared-linux-amd64"


def install(progress=print):
    if installed(): return executable()
    BIN_DIR.mkdir(parents=True, exist_ok=True); asset=_asset()
    url="https://github.com/cloudflare/cloudflared/releases/latest/download/"+asset
    progress("Downloading cloudflared (one-time remote-access setup)…")
    tmp=BIN_DIR/asset; urllib.request.urlretrieve(url,tmp)
    if asset.endswith(".exe") or (platform.system()=="Linux" and not asset.endswith((".tgz",".zip"))):
        if tmp != _exe(): os.replace(tmp,_exe())
    elif asset.endswith(".tgz"):
        with tarfile.open(tmp,"r:gz") as t:
            member=next(x for x in t.getmembers() if Path(x.name).name=="cloudflared")
            member.name="cloudflared"; t.extract(member,BIN_DIR)
        tmp.unlink(missing_ok=True)
    try: os.chmod(_exe(),0o755)
    except Exception: pass
    return executable()


def load_config():
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception: return {}


def save_config(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp=STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data,indent=2),encoding="utf-8")
    os.replace(tmp,STATE_FILE)
    try: os.chmod(STATE_FILE,0o600)
    except Exception: pass


def enabled(): return bool(load_config().get("enabled",False))
def set_enabled(v=True):
    d=load_config(); d["enabled"]=bool(v); d.setdefault("hostname",DEFAULT_HOSTNAME); save_config(d)
def hostname(): return str(load_config().get("hostname") or DEFAULT_HOSTNAME).strip().lower()
def public_url(): return "https://"+hostname()
def configure_named_tunnel(token: str, hostname_value: str=DEFAULT_HOSTNAME, enabled_value: bool=True):
    token=str(token or "").strip()
    if not token: raise ValueError("Cloudflare Tunnel token cannot be empty")
    d=load_config(); d.update({"enabled":bool(enabled_value),"mode":"named","hostname":hostname_value.strip().lower(),"tunnel_token":token})
    save_config(d)


def tunnel_token():
    return os.environ.get(TOKEN_ENV,"").strip() or str(load_config().get("tunnel_token") or "").strip()


class NamedTunnel:
    def __init__(self, local_url=DEFAULT_LOCAL_URL):
        self.local_url=local_url; self.process=None; self._thread=None
    @property
    def public_url(self): return public_url()
    def start(self, timeout=15):
        if self.process and self.process.poll() is None: return self.public_url
        token=tunnel_token()
        if not token:
            raise RuntimeError(f"Named Cloudflare Tunnel is enabled but no token is configured. Run python main.py --setup or set {TOKEN_ENV}.")
        install()
        # A remotely-managed Named Tunnel gets its ingress/hostname from the
        # Cloudflare dashboard. The token authenticates this connector; no
        # account certificate or credentials JSON is stored in the repository.
        self.process=subprocess.Popen(
            [executable(),"tunnel","--no-autoupdate","run","--token",token],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        started=threading.Event(); failed=[]
        def read():
            if not self.process or not self.process.stdout: return
            for line in self.process.stdout:
                low=line.lower()
                if "registered tunnel connection" in low or "connection" in low and "registered" in low:
                    started.set()
                if "error" in low and not started.is_set(): failed.append(line.strip())
        self._thread=threading.Thread(target=read,daemon=True,name="cloudflared-log"); self._thread.start()
        # cloudflared may take longer on slow links. A live process is enough to
        # let the dashboard start; reconnect is handled by cloudflared itself.
        started.wait(timeout)
        if self.process.poll() is not None:
            msg=failed[-1] if failed else f"cloudflared exited with code {self.process.returncode}"
            self.stop(); raise RuntimeError(msg)
        return self.public_url
    def stop(self):
        p=self.process; self.process=None
        if p and p.poll() is None:
            p.terminate()
            try: p.wait(3)
            except Exception: p.kill()

# Compatibility for older imports while upgrading V6 installations.
QuickTunnel = NamedTunnel
