"""Readable approval summaries with complete, separately reviewable arguments."""
from __future__ import annotations

import hashlib
import json

TECHNICAL_MARKER = "\n\nTechnical details:\n"


def present_action(tool: str, args: dict, reason: str = "") -> tuple[str, str]:
    operation = str(args.get("action") or args.get("capability") or args.get("operation") or "")
    target = str(args.get("output_path") or args.get("file_path") or args.get("destination")
                 or args.get("url") or args.get("app_name") or "")
    if tool == "code_helper":
        labels = {"write": "Create file", "edit": "Edit file", "run": "Run code",
                  "build": "Generate and run code", "optimize": "Modify code"}
        title = labels.get(operation, "Code operation")
    else:
        title = tool.replace("_", " ").capitalize()
    summary = [title + (": " + target if target else "")]
    if operation:
        summary.append("Operation: " + operation)
    if reason:
        summary.append("Reason: " + reason)
    fingerprints = []
    for key in ("code", "content", "script"):
        if isinstance(args.get(key), str):
            content = args[key]
            summary.append(f"File contents: {len(content)} characters (see technical details)")
            fingerprints.append(key + " SHA-256: " + hashlib.sha256(content.encode()).hexdigest())
    summary.append("Nothing has run yet. Review the technical details before approving.")
    # Full exact arguments remain available; never silently approve a truncated payload.
    technical = "Tool: " + tool + "\nArguments:\n" + json.dumps(args, ensure_ascii=False, indent=2, sort_keys=True)
    if fingerprints:
        technical += "\n" + "\n".join(fingerprints)
    return title, "\n".join(summary) + TECHNICAL_MARKER + technical
