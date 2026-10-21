"""Host-owned confirmation rules; model risk labels never grant authority."""
from __future__ import annotations

from urllib.parse import urlsplit
from pathlib import Path
from core.artifact_paths import ARTIFACT_ROOT

# These tools retain their own host/user intent or native confirmation gate.
NATIVE_GATES = {"test_flash_approval", "self_repair_apply"}
READ_ONLY = {"runtime_diagnostics", "self_repair_diagnostic", "web_search",
             "weather_report", "current_datetime", "system_status", "recall_memory", "list_paired_devices", "screen_process", "list_devices", "inspect_current_device", "get_current_device",
             "get_device_capabilities", "get_device_context", "get_devices", "list_connected_devices", "delegate_to_text_llm", "plan_with_text_llm"}
SIMPLE = {"close_camera", "open_app", "save_memory", "task_continuity"}
DEVICE_READ = {"inspect", "android.ui.inspect", "ui.inspect", "screen.inspect",
               "screen.capture", "audio.volume", "android.settings.open", "app.inspect", "app.list", "app.launch", "open_url", "browser.open",
               "browser.search", "system.info", "capabilities"}


def _ordinary_url(value) -> bool:
    value = str(value or "").strip()
    try:
        return not value or value == "about:blank" or urlsplit(value).scheme.lower() in {"", "http", "https"}
    except ValueError:
        return False


def requires_confirmation(tool: str, args: dict | None = None) -> bool:
    args = args or {}
    if tool == "server_maintenance":
        return str(args.get("operation", "status")) not in {"status", "check"}
    if tool == "document_editor":
        # This tool only reads approved documents or creates a distinct inert DOCX version.
        return str(args.get("action", "")).lower() not in {"create", "list", "inspect", "revise", "append_section"}
    if tool in READ_ONLY or tool in SIMPLE or tool in NATIVE_GATES:
        return False
    if tool == "code_helper" and str(args.get("action", "")).lower() == "write" and args.get("code"):
        raw = str(args.get("output_path") or args.get("file_path") or "")
        if raw:
            target = Path(raw)
            target = target if target.is_absolute() else ARTIFACT_ROOT / "code" / target
            try:
                target.resolve().relative_to(ARTIFACT_ROOT.resolve())
                # Text artifacts never execute; the writer creates a unique file on collision.
                if target.suffix.lower() in {".txt", ".md", ".log", ".csv", ".json"}:
                    return False
            except (ValueError, OSError):
                pass
    if tool == "skill_manager":
        # Creation/run retain host approval; listing cannot execute code.
        return args.get("operation", "list") != "list"
    if tool == "send_server_file":
        # Export allowlist/hash checks still run; ordinary delivery uses the Inbox.
        return args.get("save_direct") is True
    if tool == "browser_control":
        if not _ordinary_url(args.get("url")):
            return True
        return str(args.get("action", "")).lower() not in {"open", "search", "back", "forward", "refresh", "inspect", "screenshot", "tabs", "read"}
    if tool in {"call_current_device", "call_paired_device", "call_device"}:
        capability = str(args.get("capability") or args.get("action") or "").lower()
        device_args = args.get("args") or {}
        if not isinstance(device_args, dict):
            return True
        if capability in {"open_url", "browser.open"} and not _ordinary_url(device_args.get("url")):
            return True
        # Generic act/click/type, script execution and file writes are not read-only.
        return capability not in DEVICE_READ
    if tool == "autonomous_goal":
        return str(args.get("operation", "inspect")).lower() not in {"inspect", "resume"}
    # Unknown tools and unrestricted execution stay behind confirmation.
    return True
