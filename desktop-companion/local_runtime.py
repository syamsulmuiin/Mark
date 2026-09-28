"""Local execution bridge for MARK LIV desktop companions.
Runs the existing MARK LIV device-side tools on the companion machine so the
server refactor does not remove established computer/file/browser capabilities.
"""
from __future__ import annotations
import importlib, sys
import logging
from pathlib import Path
RUNTIME = Path(__file__).resolve().parent / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

TOOLS = {
    "open_app": ("actions.open_app", "open_app"),
    "computer_control": ("actions.computer_control", "computer_control"),
    "computer_settings": ("actions.computer_settings", "computer_settings"),
    "desktop_control": ("actions.desktop", "desktop_control"),
    "file_controller": ("actions.file_controller", "file_controller"),
    "browser_control": ("actions.browser_control", "browser_control"),
    "screen_processor": ("actions.screen_processor", "screen_processor"),
    "send_message": ("actions.send_message", "send_message"),
    "system_monitor": ("actions.system_monitor", "system_monitor"),
    "youtube_video": ("actions.youtube_video", "youtube_video"),
}

CREDENTIAL_TERMS = ("password", "passwd", "passcode", "pin", "credential", "unlock_code", "unlock code")

def _credential_target(parameters: dict) -> bool:
    def walk(value, key=""):
        key_text = str(key).lower().replace("-", "_")
        if any(term.replace(" ", "_") in key_text for term in CREDENTIAL_TERMS):
            return True
        if isinstance(value, dict):
            return any(walk(v, k) for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return any(walk(v, key) for v in value)
        if key_text in {"target", "target_text", "field", "field_name", "label", "data_type"}:
            text = str(value).lower()
            return any(term in text for term in CREDENTIAL_TERMS)
        return False
    return walk(parameters)

def invoke(tool: str, parameters: dict | None = None):
    if tool not in TOOLS:
        raise ValueError(f"unsupported local tool: {tool}")
    parameters = parameters or {}
    if _credential_target(parameters):
        return "AUTHENTICATION_REQUIRED: credential input is blocked; waiting for user instruction"
    module_name, handler_name = TOOLS[tool]
    module = importlib.import_module(module_name)
    handler = getattr(module, handler_name)
    if tool == "youtube_video":
        class LocalPlayer:
            def write_log(self, message):
                logging.getLogger("mark_liv.companion").info("%s", message)
        return handler(parameters=parameters, response=None, player=LocalPlayer(), session_memory=None)
    return handler(parameters=parameters, response=None, player=None, session_memory=None)
