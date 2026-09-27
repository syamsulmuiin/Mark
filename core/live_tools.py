"""Tool declarations whose execution is bound to Live-session state.

File-backed actions continue to self-describe from actions/*.py. Keeping the
inline Live declarations here makes main.py an orchestrator rather than a schema
warehouse without changing tool names or behaviour.
"""

TOOL_DECLARATIONS = [
    {
        "name": "task_continuity",
        "description": (
            "Maintain persistent continuity for any substantive multi-step task. Before the first action of such a task call action=begin. "
            "After a milestone is actually verified call checkpoint. If credentials/user-only authorization or a genuine unavailable capability blocks progress call block. "
            "Call complete only after the user's requested end state is verified. This is generic and must not depend on application names or task type."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": ["begin", "checkpoint", "block", "complete"]},
                "goal": {"type": "STRING"},
                "constraints": {"type": "STRING"},
                "completion_criteria": {"type": "STRING"},
                "summary": {"type": "STRING"},
                "evidence": {"type": "STRING"},
                "reason": {"type": "STRING"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "current_datetime",
        "description": (
            "Read the server's current local date and time on demand. Call this only when the user asks "
            "for the current time/date or when an operation such as resolving a relative reminder time requires it. "
            "Do not call it proactively."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "list_paired_devices",
        "description": "List trusted paired devices, their online state and permitted capabilities. Use this when you need to choose a phone or other paired target.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "transfer_file",
        "description": "Send one or more files from an online source companion to the durable attachment inbox of a paired destination companion (online or offline). For a voice request to send local files, call this tool with source omitted when the path is unknown. The source companion opens one native multi-select picker and continues the selected files as a batch. Do not request a chat upload or invent a content URI. The server verifies upload SHA-256 and size, then reports queued/notified, not saved. The recipient chooses Open, Save As or Share in its own UI. Use exact device ids/names from list_paired_devices. Source must be an accessible path or content URI. Set keep_on_server only when explicitly requested.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source_device": {"type":"STRING"},
                "destination_device": {"type":"STRING"},
                "source": {"type":"STRING", "description":"Optional accessible path/content URI for a single known file. Omit to open one native multi-select picker on the source companion."},
                "destination_name": {"type":"STRING"},
                "keep_on_server": {"type":"BOOLEAN"}
            },
            "required": ["source_device","destination_device"]
        }
    },
    {
        "name": "call_current_device",
        "description": (
            "Control the companion device that is currently talking to JARVIS. Use this for requests such as "
            "open an application, open device settings, lock this device, or perform other actions on this/current device. "
            "For opening an Android or desktop app use capability app.launch with args.app set to the natural app name. "
            "Do not use server-local open_app for a request originating from a companion when the user means this device."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "capability": {"type": "STRING", "description": "Capability exposed by the current companion"},
                "args": {
                    "type": "OBJECT",
                    "description": "Arguments for the selected device capability.",
                    "properties": {
                        "app": {"type": "STRING", "description": "Natural application name requested by the user"},
                        "name": {"type": "STRING", "description": "Alternative natural application name"},
                        "package": {"type": "STRING", "description": "Android package only when already known"},
                        "url": {"type": "STRING", "description": "URL for open_url"},
                        "page": {"type": "STRING", "description": "Android Settings page"},
                        "section": {"type": "STRING", "description": "Alternative Android Settings section"},
                        "text": {"type": "STRING", "description": "Text for UI text/click operations"},
                        "target_text": {"type": "STRING", "description": "Target field label for android.ui.text"},
                        "view_id": {"type": "STRING", "description": "Android accessibility view id"},
                        "direction": {"type": "STRING", "description": "Scroll direction"},
                        "action": {"type": "STRING", "description": "Action for android.ui.global or desktop.command"},
                        "max_nodes": {"type": "INTEGER", "description": "Maximum accessibility nodes to inspect"},
                        "tool": {"type": "STRING", "description": "Legacy desktop action tool name"},
                        "parameters": {"type": "OBJECT", "description": "Arguments passed to a legacy desktop action", "properties": {}}
                    }
                }
            },
            "required": ["capability"]
        }
    },
    {
        "name": "call_paired_device",
        "description": (
            "Control an online trusted paired device. Use natural app names with app.launch: put the app name "
            "in args.app. The companion resolves the installed application using its generic application resolver. "
            "For Android Settings use android.settings.open with optional args.page such as bluetooth, wifi, "
            "apps, accessibility, display, sound, location, security, battery, date/time, or keyboard. "
            "For any installed app, app.launch opens it by natural app name. On desktop companions app.close closes the named local application; on Android it leaves the current app and returns that device to Home because ordinary Android companions cannot force-stop arbitrary apps. Use desktop.command with args.action=lock to lock a desktop companion. On Windows/Linux/macOS companions, use capability legacy.action to run the established local MARK LIV tools without losing pre-refactor functionality. Pass args.tool as one of open_app, computer_control, computer_settings, desktop_control, file_controller, browser_control, screen_processor, send_message, or system_monitor, and put the original tool arguments in args.parameters. Use this for mouse/keyboard/window/settings/file/browser/screen/message/system operations on the target desktop. To reach a main menu, submenu, conversation, "
            "button, field, contact, or other in-app destination, use a generic inspect-reason-act-verify loop: "
            "after app.launch call android.ui.inspect BEFORE choosing the next UI action; prefer visible search controls/fields over blind scrolling. "
            "After every android.ui.click/android.ui.scroll/android.ui.text, inspect again to verify the expected screen change. "
            "If a UI action fails, inspect again and try another visible node/navigation path before asking the user. "
            "Do not claim Accessibility is disabled, Internet is down, or the device is offline unless a tool explicitly reports that cause. "
            "Keep using the device the user explicitly selected; never offer or silently switch to the PC/server merely because an Android UI step failed. "
            "Use open_url when the user provides a supported deep link/URL shortcut. For Android Settings use "
            "android.settings.open for direct system pages, otherwise inspect/click through nested pages. Use "
            "android.screen.lock to lock the phone and android.screen.wake only to wake the display. Continue ordinary UI automation through navigation, text, and Send/Submit without asking the user to take over. "
            "Never type, paste, generate, retrieve, infer, or submit a PIN, password, passcode, unlock code, or other authentication credential. If credential authentication is encountered, stop before credential entry, preserve the current screen/session, report that authentication is waiting, and wait for the user's next instruction. "
            "Never invent a package name when the user supplied an app name."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device_id": {"type": "STRING", "description": "Exact device_id returned by list_paired_devices, or its exact device name. Never invent a numeric id; call list_paired_devices first when the target is not the current companion."},
                "capability": {"type": "STRING", "description": "Capability exposed by that device"},
                "args": {
                    "type": "OBJECT",
                    "description": "Arguments for the selected device capability.",
                    "properties": {
                        "app": {"type": "STRING", "description": "Natural application name requested by the user"},
                        "name": {"type": "STRING", "description": "Alternative natural application name"},
                        "package": {"type": "STRING", "description": "Android package only when already known"},
                        "url": {"type": "STRING", "description": "URL for open_url"},
                        "page": {"type": "STRING", "description": "Android Settings page"},
                        "section": {"type": "STRING", "description": "Alternative Android Settings section"},
                        "text": {"type": "STRING", "description": "Text for UI text/click operations"},
                        "target_text": {"type": "STRING", "description": "Target field label for android.ui.text"},
                        "view_id": {"type": "STRING", "description": "Android accessibility view id"},
                        "direction": {"type": "STRING", "description": "Scroll direction"},
                        "action": {"type": "STRING", "description": "Action for android.ui.global or desktop.command"},
                        "max_nodes": {"type": "INTEGER", "description": "Maximum accessibility nodes to inspect"},
                        "tool": {"type": "STRING", "description": "Legacy desktop action tool name"},
                        "parameters": {"type": "OBJECT", "description": "Arguments passed to a legacy desktop action", "properties": {}}
                    }
                }
            },
            "required": ["device_id", "capability"]
        }
    },
    # ── Inline tools ─────────────────────────────────────────────────────────
    # These stay here (rather than in an actions/*.py TOOL dict) because their
    # handling is woven into live-session state — vision capture/injection,
    # camera stream, memory writes, the monitor engine, and shutdown. All other
    # tools live in their own action file and are auto-discovered by
    # core.action_loader (see JarvisLive.__init__).
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "For companion camera capture, a real one-shot frame is captured directly and the Camera app does not need to open. A server-local camera preview, when explicitly targeting the server, stays open until the user closes it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for a real camera frame. Default: 'screen'"},
                "facing": {"type": "STRING", "description": "For camera capture on a companion: 'front' or 'back'. Default: 'back'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when the user says (in ANY language): close camera, stop camera, "
            "turn off camera, that's creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background monitoring topics. "
            "JARVIS checks these topics once a day and alerts the user when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what is being monitored. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
# EXPLICIT SERVER SHUTDOWN ONLY: never use for ending a conversation/session or farewell intent.
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Look up a fact you have stored about the user but which is NOT in "
            "the memory block of your system prompt. "
            "The prompt lists the keys it did not have room for under "
            "'[ALSO REMEMBERED]' — if the user asks about anything named there, "
            "call this FIRST. "
            "Also call it before saying you do not know something personal, and "
            "when the user asks what you remember about them (leave query empty "
            "for everything). "
            "This is a local file search: it is instant and costs nothing."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Keyword to search for — a name, a topic, a category "
                        "(e.g. 'ayse', 'coffee', 'projects'). "
                        "Leave empty to list everything stored."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "undo",
        "description": (
            "Reverse the last change YOU made to this computer — a file you "
            "moved, renamed, created or wrote, or a setting you changed such as "
            "volume, brightness, dark mode or WiFi. "
            "Call this whenever the user says undo, revert, take it back, put it "
            "back, cancel that, or tells you that you did the wrong thing, in ANY "
            "language. "
            "Use action='list' when they ask what can be undone. "
            "This only covers your own actions — it is not the Ctrl+Z of whatever "
            "application is on screen (that is computer_settings with action 'undo')."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "undo (default) — reverse the last change | list — show what can be undone",
                },
            },
            "required": [],
        },
    },
]

