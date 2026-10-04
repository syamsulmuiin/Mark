"""Headless assistant server process lifecycle and admin CLI.

Kept separate from the Live conversation runtime so start/stop/autostart/pairing
maintenance does not add coupling to main.py.
"""
from __future__ import annotations

import os
import sys
import subprocess as _subprocess
from pathlib import Path
from core.network_config import LOCAL_BASE_URL, DASHBOARD_PORT

BASE_DIR = Path(__file__).resolve().parent.parent
MAIN_FILE = BASE_DIR / "main.py"

def _runtime_paths():
    runtime = BASE_DIR / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime / "server.pid", runtime / "error.log"

def _pid_alive(pid):
    try:
        if sys.platform == "win32":
            r = _subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
                capture_output=True, text=True, timeout=5,
            )
            return r.returncode == 0 and r.stdout.strip() == str(int(pid))
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def _is_markliv_worker(pid):
    """Never terminate an unrelated process just because a stale PID file exists.

    Prefer psutil because it is already a server dependency and is more reliable
    than shell command-line inspection on Windows. Keep the OS-specific probe as
    a dependency/runtime fallback.
    """
    try:
        import psutil
        proc = psutil.Process(int(pid))
        cmd = " ".join(proc.cmdline()).lower().replace("/", "\\")
        if "main.py" in cmd and "--server-worker" in cmd:
            return True
    except Exception:
        pass
    try:
        if sys.platform == "win32":
            ps = (
                f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' -ErrorAction SilentlyContinue; "
                "$p.CommandLine"
            )
            r = _subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=5)
            cmd = (r.stdout or "").lower().replace("/", "\\")
        else:
            r = _subprocess.run(["ps", "-p", str(int(pid)), "-o", "command="], capture_output=True, text=True, timeout=5)
            cmd = (r.stdout or "").lower()
        return "main.py" in cmd and "--server-worker" in cmd
    except Exception:
        return False

def _read_pidfile():
    pidfile, _ = _runtime_paths()
    try:
        return int(pidfile.read_text(encoding="utf-8").strip())
    except Exception:
        return None

def _local_server_identity(timeout=1.0):
    """Return the PID reported by the assistant server, or None.

    Process command-line inspection on Windows proved intermittent.  The local
    health endpoint is a stronger identity check because only this server exposes
    the endpoint and it reports its own OS PID.
    """
    try:
        import urllib.request as _ur, json as _json
        req = _ur.Request(f"{LOCAL_BASE_URL}/api/local/health", headers={"X-Jarvis-Local": "1"})
        with _ur.urlopen(req, timeout=timeout) as r:
            data = _json.loads(r.read().decode("utf-8"))
        if data.get("service") == "MARK-LIV" and data.get("status") == "ready":
            return int(data.get("pid"))
    except Exception:
        return None
    return None

def _server_pid():
    pidfile, _ = _runtime_paths()
    file_pid = _read_pidfile()
    service_pid = _local_server_identity()
    if not service_pid and file_pid and _pid_alive(file_pid):
        # The dashboard event loop can be briefly busy while Live audio/tools are
        # active. A transient health timeout must not turn a live worker into a
        # false "server is not running" result.
        service_pid = _local_server_identity(timeout=2.0)
    if service_pid and _pid_alive(service_pid):
        # Self-heal a missing/stale PID file from the running MARK-LIV server.
        if file_pid != service_pid:
            try: pidfile.write_text(str(service_pid), encoding="utf-8")
            except Exception: pass
        return service_pid
    # During early startup the HTTP endpoint may not exist yet.  Accept the PID
    # file only when the worker command line can positively identify it.
    if file_pid and _pid_alive(file_pid) and _is_markliv_worker(file_pid):
        return file_pid
    if file_pid and not _pid_alive(file_pid):
        pidfile.unlink(missing_ok=True)
    return None

def _local_server_ready(timeout=0.8):
    return _local_server_identity(timeout=timeout) is not None

def _spawn_server():
    import time as _time
    pidfile, logfile = _runtime_paths()
    if (pid := _server_pid()):
        print(f"MARK LIV server already running (PID {pid}).")
        return pid
    # Do not overwrite lifecycle state if the configured dashboard port belongs to another process.
    if _local_server_ready():
        print(f"MARK LIV cannot start: port {DASHBOARD_PORT} is already in use. Stop the existing service first.")
        return None
    pidfile.unlink(missing_ok=True)
    # The worker owns severity-filtered runtime/error.log through a rotating sink.
    # Keep inherited stdio detached so Windows does not hold the active log open
    # and block atomic rollover/rename.
    kwargs = dict(stdin=_subprocess.DEVNULL, stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL, cwd=str(BASE_DIR))
    if sys.platform == "win32":
        kwargs["creationflags"] = _subprocess.CREATE_NEW_PROCESS_GROUP | _subprocess.DETACHED_PROCESS | _subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    p = _subprocess.Popen([sys.executable, str(MAIN_FILE), "--server-worker"], **kwargs)
    # Popen returns the actual --server-worker PID.  Startup success must track
    # that worker lifecycle, not an HTTP endpoint: the dashboard/API can become
    # ready slightly later while the long-lived worker is already healthy.
    # The worker remains the owner of server.pid; wait only for that ownership
    # hand-off and never report a false startup failure because HTTP is late.
    deadline = _time.monotonic() + 15.0
    while _time.monotonic() < deadline:
        if p.poll() is not None:
            print(f"MARK LIV server failed to start (exit code {p.returncode}). Check runtime/error.log.")
            return None
        file_pid = _read_pidfile()
        if file_pid == p.pid and _pid_alive(p.pid):
            print(f"MARK LIV server started (PID {p.pid}).")
            return p.pid
        _time.sleep(0.2)
    # A live worker is still a successful server start even if PID-file I/O was
    # delayed/blocked.  Repair the local lifecycle state from the child we just
    # created instead of spawning a duplicate on the next --start.
    if p.poll() is None and _pid_alive(p.pid):
        try:
            pidfile.write_text(str(p.pid), encoding="utf-8")
        except Exception:
            pass
        print(f"MARK LIV server started (PID {p.pid}).")
        return p.pid
    print("MARK LIV server failed to start. Check runtime/error.log.")
    return None


def _pair_device(pairing_id: str | None = None):
    """Issue a one-time operator code for an existing companion request."""
    if not _server_pid() or not _local_server_ready():
        print("MARK LIV server is not running. Start it first with --start.")
        return
    try:
        import urllib.request as _ur, json as _json
        if not pairing_id:
            req = _ur.Request(f"{LOCAL_BASE_URL}/api/local/pairing/pending", method="GET", headers={"X-Jarvis-Local": "1"})
            with _ur.urlopen(req, timeout=3) as r:
                data = _json.loads(r.read().decode("utf-8"))
            print(_json.dumps(data, indent=2))
            print("Use --pairing-id <id> to issue one code after reviewing the request.")
            return
        payload = _json.dumps({"pairing_id": pairing_id}).encode("utf-8")
        req = _ur.Request(f"{LOCAL_BASE_URL}/api/local/pairing/new", data=payload, method="POST", headers={"X-Jarvis-Local": "1", "Content-Type": "application/json"})
        with _ur.urlopen(req, timeout=3) as r:
            data = _json.loads(r.read().decode("utf-8"))
        print(f"MARK LIV Pair Code: {data['code']}")
        print(f"Pairing request: {data['pairing_id']}")
        print("Code is one-time and expires with the pairing request.")
    except Exception as exc:
        print(f"Could not create Pair Code: {exc}")

def _stop_server():
    import signal, time as _time
    pidfile, _ = _runtime_paths()
    pid = _server_pid()
    if not pid:
        pidfile.unlink(missing_ok=True)
        print("MARK LIV server is not running.")
        return
    # The local HTTP identity is useful when available, but it must not be a
    # prerequisite for stopping the worker: dashboard readiness and worker
    # lifecycle are separate concerns.  Verify the OS process command line
    # instead so a stale PID can never terminate an unrelated process.
    service_pid = _local_server_identity()
    if service_pid != pid and not _is_markliv_worker(pid):
        print(f"Refusing to stop PID {pid}: process is not a MARK LIV server worker.")
        return
    if sys.platform == "win32":
        r = _subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=10)
        if r.returncode and _pid_alive(pid):
            print(f"Could not stop MARK LIV server PID {pid}: {(r.stderr or r.stdout).strip()}")
            return
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = _time.monotonic() + 5.0
    while _time.monotonic() < deadline and _pid_alive(pid):
        _time.sleep(0.1)
    if _pid_alive(pid):
        print(f"MARK LIV server PID {pid} did not stop cleanly.")
        return
    pidfile.unlink(missing_ok=True)
    print(f"MARK LIV server stopped (PID {pid}).")

def _autostart_enable():
    """Install per-user autostart without adding another runtime mode."""
    py=str(Path(sys.executable).resolve()); main=str(MAIN_FILE)
    if sys.platform == "win32":
        name="MARK-LIV-Server"
        cmd=f'"{py}" "{main}" --start'
        r=_subprocess.run(["schtasks","/Create","/TN",name,"/SC","ONLOGON","/TR",cmd,"/F"],capture_output=True,text=True)
        if r.returncode: raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    elif sys.platform == "darwin":
        target=Path.home()/"Library/LaunchAgents/com.markliv.server.plist"; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>Label</key><string>com.markliv.server</string><key>ProgramArguments</key><array><string>{py}</string><string>{main}</string><string>--start</string></array><key>RunAtLoad</key><true/></dict></plist>',encoding="utf-8")
        _subprocess.run(["launchctl","unload",str(target)],capture_output=True)
        _subprocess.run(["launchctl","load",str(target)],check=True)
    else:
        target=Path.home()/".config/systemd/user/mark-liv.service"; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(f"[Unit]\nDescription=MARK LIV Server\n\n[Service]\nType=oneshot\nExecStart={py} {main} --start\nRemainAfterExit=yes\nExecStop={py} {main} --stop\n\n[Install]\nWantedBy=default.target\n",encoding="utf-8")
        _subprocess.run(["systemctl","--user","daemon-reload"],check=True)
        _subprocess.run(["systemctl","--user","enable","mark-liv.service"],check=True)
    print("MARK LIV autostart enabled."); _spawn_server()

def _autostart_disable():
    if sys.platform == "win32":
        _subprocess.run(["schtasks","/Delete","/TN","MARK-LIV-Server","/F"],capture_output=True)
    elif sys.platform == "darwin":
        target=Path.home()/"Library/LaunchAgents/com.markliv.server.plist"
        _subprocess.run(["launchctl","unload",str(target)],capture_output=True); target.unlink(missing_ok=True)
    else:
        _subprocess.run(["systemctl","--user","disable","mark-liv.service"],capture_output=True)
        (Path.home()/".config/systemd/user/mark-liv.service").unlink(missing_ok=True)
        _subprocess.run(["systemctl","--user","daemon-reload"],capture_output=True)
    print("MARK LIV autostart disabled. Running server, if any, is left unchanged; use --stop to stop it.")

def _runtime_mode(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description="MARK LIV server")
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--start",action="store_true",help="start server")
    g.add_argument("--enable",action="store_true",help="enable autostart and start server")
    g.add_argument("--stop",action="store_true",help="stop server")
    g.add_argument("--disable",action="store_true",help="disable autostart")
    g.add_argument("--pair",action="store_true",help="list pending companion pairing requests or issue a code")
    parser.add_argument("--pairing-id", help="pending pairing request ID to approve")
    g.add_argument("--server-worker",action="store_true",help=argparse.SUPPRESS)
    a=parser.parse_args(argv)
    if a.start:return "start"
    if a.enable:return "enable"
    if a.stop:return "stop"
    if a.disable:return "disable"
    if a.pair:return f"pair:{a.pairing_id or ''}"
    return "worker"

