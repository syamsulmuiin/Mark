"""Runtime interfaces for JARVIS UI, CLI and background modes.

The live brain talks to this small surface instead of requiring Qt to exist.
The desktop JarvisUI already implements the same attributes; CLI/background use
HeadlessInterface below. Irreversible actions remain protected: background mode
has no confirmation surface, while CLI confirmations require /confirm.
"""
from __future__ import annotations
import json
import sys
import threading
import time
from pathlib import Path

class _ReadyWindow:
    _ready = True

class HeadlessInterface:
    def __init__(self, cli: bool = False):
        self.cli = cli
        self.muted = False
        self.current_file = None
        self._win = _ReadyWindow()
        self.on_text_command = None
        self.on_push_to_talk = None
        self.ptt_hold = None
        self.on_remote_clicked = None
        self.on_interrupt = None
        self.on_voice_change = None
        self.on_audio_device_change = None
        self.get_plugins = lambda: []
        self.get_plugin_settings = lambda: {}
        self.request_say = None
        self.wake_is_ready = lambda: False
        self.wake_get_state = lambda: {}
        self.on_wake_toggle = None
        self.on_wake_manual = None
        self.on_wake_install = None
        self._stop = threading.Event()

    def write_log(self, text):
        print(str(text), flush=True)
    def set_state(self, state):
        if self.cli: print(f"[STATE] {state}", flush=True)
    def set_audio_level(self, *_): pass
    def push_visemes(self, *_): pass
    def start_camera_stream(self): pass
    def stop_camera_stream(self): pass
    def show_content(self, label, content):
        print(f"\n--- {label} ---\n{content}\n", flush=True)
    def notify_phone_connected(self):
        self.write_log("SYS: Paired/remote device connected.")
    def hide_confirm(self): pass
    def show_confirm(self, title, detail):
        if not self.cli:
            raise RuntimeError("background mode has no human confirmation surface")
        self.write_log(f"CONFIRM REQUIRED: {title}\n{detail}\nType /confirm or /cancel.")
    def wait_for_api_key(self):
        from core.setup_config import configured, interactive_setup
        if configured():
            return
        if self.cli and interactive_setup():
            return
        raise RuntimeError("JARVIS is not configured. Run: python main.py --setup")
    def prompt_reconfig(self):
        self.write_log("ERR: API key must be reconfigured. Run: python main.py --setup")
    def run_cli(self):
        from core import confirm
        self.write_log("SYS: CLI ready. Type a command, /confirm, /cancel, or /quit.")
        while not self._stop.is_set():
            try: line = input("jarvis> ").strip()
            except (EOFError, KeyboardInterrupt): break
            if not line: continue
            if line == "/quit": break
            if line == "/confirm": confirm.resolve(True); continue
            if line == "/cancel": confirm.resolve(False); continue
            cb = self.on_text_command
            if cb: cb(line)
            else: self.write_log("SYS: Brain is still starting; try again shortly.")
        self._stop.set()

    def __getattr__(self, name):
        # Optional visual-only hooks are intentionally harmless in non-UI modes.
        if name.startswith(("set_", "show_", "hide_", "notify_", "update_")):
            return lambda *a, **k: None
        raise AttributeError(name)


class ServerInterface(HeadlessInterface):
    """Non-interactive server surface. No CLI, microphone, speaker, or desktop UI."""
    def __init__(self):
        super().__init__(cli=False)
    def write_log(self, text):
        print(str(text), flush=True)
    def show_confirm(self, title, detail):
        raise RuntimeError("Confirmation requires an authenticated companion client")
    def wait_for_api_key(self):
        from core.setup_config import configured
        if not configured():
            raise RuntimeError("MARK LIV server is not configured. Run setup.py before --start.")
