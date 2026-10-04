"""User-created recurring JARVIS workflows.

No built-in schedules live here. Entries exist only after an explicit user request.
The live runtime executes due workflows so compound commands can use normal tools
(news, device control, etc.) at execution time instead of being reduced to a toast.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()
_STORE = Path.home() / ".jarvis" / "scheduled_workflows.json"


def _load() -> list[dict]:
    with _LOCK:
        try:
            data = json.loads(_STORE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []


def _save(items: list[dict]) -> None:
    with _LOCK:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_STORE)


def due_workflows(now: datetime | None = None) -> list[dict]:
    """Atomically claim daily workflows due this minute; safe across reconnects."""
    now = now or datetime.now()
    today = now.date().isoformat()
    hhmm = now.strftime("%H:%M")
    due: list[dict] = []
    items = _load()
    changed = False
    for item in items:
        if not item.get("enabled", True) or item.get("repeat") != "daily":
            continue
        if item.get("time") == hhmm and item.get("last_run_date") != today:
            item["last_run_date"] = today
            due.append(dict(item))
            changed = True
    if changed:
        _save(items)
    return due


def scheduled_workflow(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "create")).strip().lower()
    items = _load()

    if action == "list":
        active = [x for x in items if x.get("enabled", True)]
        if not active:
            return "No user-created recurring workflows are scheduled."
        return "\n".join(
            f"{x['id']}: daily {x['time']} — {x['command']}" for x in active
        )

    if action == "cancel":
        workflow_id = str(parameters.get("workflow_id", "")).strip()
        if not workflow_id:
            return "workflow_id is required to cancel a scheduled workflow."
        found = False
        for item in items:
            if item.get("id") == workflow_id:
                item["enabled"] = False
                found = True
        if found:
            _save(items)
            return f"Scheduled workflow {workflow_id} cancelled."
        return f"Scheduled workflow {workflow_id} was not found."

    time_text = str(parameters.get("time", "")).strip()
    command = str(parameters.get("command", "")).strip()
    try:
        datetime.strptime(time_text, "%H:%M")
    except ValueError:
        return "A daily workflow needs time in HH:MM 24-hour format."
    if not command:
        return "A scheduled workflow needs a command to execute."

    device_id = None
    try:
        if player and player._dashboard:
            device_id = player._dashboard.active_voice_device()
    except Exception:
        pass

    workflow_id = uuid.uuid4().hex[:8]
    items.append({
        "id": workflow_id,
        "repeat": "daily",
        "time": time_text,
        "command": command,
        "device_id": device_id,
        "enabled": True,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "last_run_date": None,
    })
    _save(items)
    target = " on the requesting companion" if device_id else ""
    return f"Daily JARVIS workflow {workflow_id} scheduled for {time_text}{target}."


TOOL = {
    "name": "scheduled_workflow",
    "description": (
        "Creates, lists, or cancels USER-REQUESTED recurring JARVIS workflows. "
        "Use this for requests such as 'every morning at 07:00 greet me and read the latest news'. "
        "The command is executed by JARVIS at run time and may use normal tools. "
        "Do not create schedules unless the user explicitly asks for recurrence."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "create | list | cancel"},
            "time": {"type": "STRING", "description": "Daily time HH:MM (24-hour), required for create"},
            "command": {"type": "STRING", "description": "Full instruction JARVIS must execute each day"},
            "workflow_id": {"type": "STRING", "description": "ID returned by create; required for cancel"},
        },
        "required": ["action"],
    },
    "handler": scheduled_workflow,
}
