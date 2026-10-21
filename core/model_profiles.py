"""Explicit capability routes over a single pool of user-approved model profiles."""

from __future__ import annotations

import getpass
import json
import os
import re
import tempfile
import time

from core.setup_config import load_config

CAPABILITIES = {
    "text": "Text and reasoning",
    "vision": "Read/review images",
    "image": "Generate images",
    "live": "Live voice conversation",
}
ADAPTERS = {
    "gemini": {"text", "vision", "image", "live"},
    "openai": {"text", "vision", "image"},
    "openai_codex": {"text", "vision"},
    "anthropic": {"text", "vision"},
    "deepseek": {"text"},
    "google_oauth": {"text", "vision"},
    "openrouter": {"text", "vision"},
    "ollama_local": {"text", "vision"},
    "ollama_cloud": {"text", "vision"},
    "openai_realtime": {"live"},
    "nvidia": {"image"},
}


class RouteUnavailable(RuntimeError):
    pass


def enabled(settings):
    return (
        isinstance(settings.get("model_routing"), dict)
        and settings["model_routing"].get("enabled") is True
    )


def validate(policy):
    if (
        not isinstance(policy, dict)
        or not isinstance(policy.get("profiles"), list)
        or len(policy["profiles"]) > 20
    ):
        raise ValueError("Invalid model profile pool")
    seen = {}
    for p in policy["profiles"]:
        if (
            not isinstance(p, dict)
            or not isinstance(p.get("id"), str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", p["id"])
            or p["id"] in seen
            or not isinstance(p.get("provider"), str)
            or p.get("provider") not in ADAPTERS
            or not isinstance(p.get("model"), str)
            or not re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", p["model"])
            or not isinstance(p.get("capabilities"), list)
            or not p["capabilities"]
            or not all(
                isinstance(c, str) and c in ADAPTERS[p["provider"]]
                for c in p["capabilities"]
            )
            or not isinstance(p.get("api_key", ""), str)
            or not isinstance(p.get("description", ""), str)
            or len(p.get("description", "")) > 200
        ):
            raise ValueError("Invalid or unsupported model profile capability")
        if p["provider"] == "gemini" and not re.fullmatch(
            r"[A-Za-z0-9._-]{1,150}", p["model"]
        ):
            raise ValueError("Invalid Gemini model ID")
        if "image" in p["capabilities"]:
            from core.image_generation import selection

            selection(
                {
                    "image_generation": {
                        "provider": p["provider"],
                        "model": p["model"],
                        "api_key": p.get("api_key", ""),
                    }
                }
            )
        seen[p["id"]] = p
    routes = policy.get("routes")
    if not isinstance(routes, dict) or set(routes) - set(CAPABILITIES):
        raise ValueError("Audio/video generation adapters are not implemented")
    for role, ids in routes.items():
        if (
            not isinstance(ids, list)
            or len(ids) > 4
            or any(not isinstance(i, str) for i in ids)
            or len(set(ids)) != len(ids)
            or any(
                not isinstance(i, str)
                or i not in seen
                or role not in seen[i]["capabilities"]
                for i in ids
            )
        ):
            raise ValueError("Route contains an unapproved or incompatible profile")
        if role == "live" and len(ids) > 1:
            raise ValueError(
                "Live requires one profile; cross-provider session failover is not implemented"
            )
    failover = policy.get("failover", [])
    if not isinstance(failover, list) or any(
        not isinstance(c, str) or c not in {"text", "vision", "image"} for c in failover
    ):
        raise ValueError("Invalid failover capabilities")
    return policy


def candidates(role, settings):
    if role not in CAPABILITIES:
        raise RouteUnavailable("No implemented adapter for capability " + str(role))
    policy = validate(settings.get("model_routing"))
    pool = {p["id"]: p for p in policy["profiles"]}
    ids = policy["routes"].get(role, [])
    if not ids:
        raise RouteUnavailable("No approved model configured for " + role)
    return [pool[i] for i in ids]


def primary(role, settings):
    return candidates(role, settings)[0]


def _safe_next(role, error):
    # Image requests can already be charged/completed after a timeout. Safety
    # refusals and malformed/partial output never authorize another generation.
    message = str(error)
    if role == "image":
        return message in {
            "image_provider_http_401",
            "image_provider_http_404",
            "image_provider_http_429",
        }
    if isinstance(error, RouteUnavailable):
        return True
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    return bool(re.search(r"\bHTTP (?:401|404|429|500|502|503|504)\b", message))


def run(role, invoke, *, settings=None, timeout=120):
    settings = load_config() if settings is None else settings
    profiles = candidates(role, settings)
    policy = settings["model_routing"]
    if role not in policy.get("failover", []):
        profiles = profiles[:1]
    deadline = time.monotonic() + timeout
    from core.interaction_log import write_event
    from core import setup_config

    for attempt, p in enumerate(profiles, 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Approved model route budget exhausted")
        fields = {
            "capability": role,
            "profile_id": p["id"],
            "provider": p["provider"],
            "model": p["model"],
            "attempt": attempt,
        }
        write_event(
            setup_config.BASE_DIR / "runtime/interaction.log",
            "model_route",
            stage="started",
            **fields,
        )
        try:
            result = invoke(p, remaining)
        except Exception as exc:
            write_event(
                setup_config.BASE_DIR / "runtime/interaction.log",
                "model_route",
                stage="failed",
                error_type=type(exc).__name__,
                **fields,
            )
            if attempt == len(profiles) or not _safe_next(role, exc):
                raise
        else:
            write_event(
                setup_config.BASE_DIR / "runtime/interaction.log",
                "model_route",
                stage="succeeded",
                **fields,
            )
            return result
    raise RouteUnavailable("No approved model completed this capability")


def snapshot(settings=None):
    settings = load_config() if settings is None else settings
    if not enabled(settings):
        return {"enabled": False, "mode": "legacy_primary_only"}
    policy = validate(settings["model_routing"])
    return {
        "enabled": True,
        "profiles": [
            {
                k: p.get(k)
                for k in ("id", "provider", "model", "capabilities", "description")
            }
            for p in policy["profiles"]
        ],
        "routes": policy["routes"],
        "failover": policy.get("failover", []),
        "unavailable": ["video_generation", "audio_music_generation"],
        "live_failover": False,
        "capability_verification": "adapter support; actual model/access checked at runtime",
    }


def from_legacy(settings):
    profiles = []
    routes = {}

    def add(identifier, provider, model, caps, key=""):
        if not model:
            return
        profiles.append(
            {
                "id": identifier,
                "provider": provider,
                "model": model,
                "capabilities": caps,
                "api_key": key,
                "description": "Imported current selection; runtime capability/access not certified",
            }
        )
        for role in caps:
            routes.setdefault(role, []).append(identifier)

    text_provider = settings.get("llm_provider", "gemini")
    if text_provider == "gemini":
        from core.model_config import get_chat_models

        text_model = (
            str(
                settings.get("chat_models")
                or settings.get("text_models")
                or get_chat_models()[0]
            )
            .split(",")[0]
            .strip()
        )
    else:
        text_model = (
            str(
                (settings.get("provider_models") or {}).get(text_provider)
                or settings.get("chat_models")
                or settings.get("text_models")
                or ""
            )
            .split(",")[0]
            .strip()
        )
    caps = ["text"] + (
        ["vision"]
        if text_provider in ADAPTERS and "vision" in ADAPTERS[text_provider]
        else []
    )
    add(
        "current_text",
        text_provider,
        text_model,
        caps,
        str(settings.get(text_provider + "_api_key") or ""),
    )
    live_provider = settings.get("live_provider", "gemini")
    from core.model_config import get_live_models

    live_model = (
        str(settings.get("realtime_model") or "gpt-realtime-2.1")
        if live_provider == "openai_realtime"
        else str(settings.get("live_models") or get_live_models()[0])
        .split(",")[0]
        .strip()
    )
    add(
        "current_live",
        live_provider,
        live_model,
        ["live"],
        str(
            settings.get(
                "openai_api_key"
                if live_provider == "openai_realtime"
                else "gemini_api_key"
            )
            or ""
        ),
    )
    image = settings.get("image_generation") or {}
    if isinstance(image, dict) and image.get("provider") in {
        "gemini",
        "openai",
        "nvidia",
    }:
        add(
            "current_image",
            image["provider"],
            str(image.get("model") or ""),
            ["image"],
            str(image.get("api_key") or ""),
        )
    return {"enabled": True, "profiles": profiles, "routes": routes, "failover": []}


def save(policy):
    from core import setup_config

    validate(policy)
    path = setup_config.CONFIG_FILE
    current = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(current, dict):
        raise ValueError("Invalid server configuration; refusing overwrite")
    current["model_routing"] = policy
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as output:
        temp = output.name
        json.dump(current, output, ensure_ascii=False, indent=4)
    try:
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def discover_models(provider, key, caps):
    """Best-effort discovery; catalog visibility does not certify capabilities."""
    try:
        if "image" in caps:
            from core.image_generation import list_image_models

            return list_image_models(provider, key)
        if provider == "openai_codex":
            from core.llm_codex import list_models

            return sorted({m["id"] for m in list_models()})
        if provider in {"gemini", "openai"}:
            from core.image_generation import _request

            if provider == "openai":
                data = _request(
                    provider, key, "https://api.openai.com/v1/models", timeout=20
                )
                return sorted(
                    {
                        m["id"]
                        for m in data.get("data", [])
                        if isinstance(m.get("id"), str)
                    }
                )
            data = _request(
                provider,
                key,
                "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100",
                timeout=20,
            )
            return sorted(
                {
                    m["name"].removeprefix("models/")
                    for m in data.get("models", [])
                    if isinstance(m.get("name"), str)
                }
            )
    except Exception:
        print(
            "Catalog unavailable. Enter an exact model ID; existing configuration is unchanged."
        )
    return []


PROVIDER_NAMES = {
    "gemini": "Google Gemini",
    "openai": "OpenAI API",
    "openai_codex": "OpenAI / Codex account",
    "anthropic": "Anthropic Claude API",
    "deepseek": "DeepSeek",
    "google_oauth": "Google Gemini OAuth",
    "openrouter": "OpenRouter",
    "ollama_local": "Ollama local",
    "ollama_cloud": "Ollama cloud",
    "openai_realtime": "OpenAI Realtime",
    "nvidia": "NVIDIA hosted image generation",
}
TASK_NAMES = {
    "text": "Text / reasoning",
    "live": "Live / voice",
    "vision": "Image reading / review",
    "image": "Image generation",
}


def _profile_label(profile):
    return f"{PROVIDER_NAMES[profile['provider']]} / {profile['model']}"


def _show_settings(policy, active):
    print("\nMARK MODEL SETTINGS")
    print("Changes are saved only with Save and exit.")
    print(
        "Current mode: "
        + (
            "Model profiles"
            if active
            else "Standard Text + Live; profiles below are a draft"
        )
    )
    print("\nTask assignments")
    pool = {p["id"]: p for p in policy["profiles"]}
    for role, label in TASK_NAMES.items():
        ids = policy["routes"].get(role, [])
        names = [_profile_label(pool[i]) for i in ids if i in pool]
        print(f"  {label}: " + (" -> ".join(names) if names else "Not configured"))
        if len(names) > 1:
            print(
                "    Automatic alternatives: "
                + ("enabled" if role in policy.get("failover", []) else "disabled")
            )
    print("\nModel list (draft)")
    for number, p in enumerate(policy["profiles"], 1):
        uses = ", ".join(TASK_NAMES[c] for c in p["capabilities"])
        print(f"  {number}. {_profile_label(p)}")
        print(f"     Tasks: {uses}")
        if not any(p['id'] in ids for ids in policy['routes'].values()):
            print('     Not assigned. Choose option 2 to use this model for a task.')
        description = p.get("description", "")
        if description and not description.startswith("Imported current selection;"):
            print("     " + description)
    if not policy["profiles"]:
        print("  No models added.")
    print(
        "\n  1. Add a model\n  2. Choose models for tasks\n  3. Save and exit"
        "\n  4. Cancel without saving\n  5. Remove a model\n  6. Restore standard Text + Live settings"
    )


def _numbers(value, maximum, *, multiple=False):
    values = value.split(",") if multiple else [value]
    if not values or any(not v.strip().isdigit() for v in values):
        raise ValueError(
            "Enter a displayed model number"
            + (" or comma-separated numbers." if multiple else ".")
        )
    numbers = [int(v.strip()) for v in values]
    if any(n < 1 or n > maximum for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError("Choose distinct numbers from the displayed list.")
    return numbers


def _add_profile(policy, settings, ask):
    print("\nADD MODEL — 1/3: Provider")
    providers = list(ADAPTERS)
    for number, provider in enumerate(providers, 1):
        print(f"  {number}. {PROVIDER_NAMES[provider]}")
        print(
            "     "
            + ", ".join(TASK_NAMES[c] for c in TASK_NAMES if c in ADAPTERS[provider])
        )
    provider = providers[
        _numbers(ask("Provider number: ").strip(), len(providers))[0] - 1
    ]
    print("\nADD MODEL — 2/3: Intended tasks")
    caps = [c for c in TASK_NAMES if c in ADAPTERS[provider]]
    for number, role in enumerate(caps, 1):
        print(f"  {number}. {TASK_NAMES[role]}")
    print(
        "Select only tasks supported by the actual model. API access is checked when used."
    )
    value = ask("Task numbers, separated by commas [1]: ").strip() or "1"
    selected = [caps[n - 1] for n in _numbers(value, len(caps), multiple=True)]
    key = ""
    if provider in {"openai_codex", "google_oauth"}:
        from core.setup_config import authenticate_account

        authenticate_account(provider)
    elif provider != "ollama_local":
        existing = next(
            (
                p.get("api_key", "")
                for p in policy["profiles"]
                if p["provider"] == provider and p.get("api_key")
            ),
            "",
        )
        existing = existing or str(
            settings.get(
                ("openai" if provider == "openai_realtime" else provider) + "_api_key"
            )
            or ""
        )
        if existing and ask(
            "Use the saved API key for this provider? [Y/n]: "
        ).strip().lower() not in {"n", "no"}:
            key = existing
        else:
            key = getpass.getpass("API key (hidden): ").strip()
        if not key:
            raise ValueError("An API key is required for this provider.")
    print("\nADD MODEL — 3/3: Model")
    models = discover_models(provider, key, selected)
    for number, name in enumerate(models, 1):
        print(f"  {number}. {name}")
    if not models:
        print("No catalog available. Enter the exact model ID from your provider.")
    value = ask("Model number or exact model ID: ").strip()
    model = models[_numbers(value, len(models))[0] - 1] if value.isdigit() else value
    identifier = next(
        "model_" + str(i)
        for i in range(1, 100)
        if not any(p["id"] == "model_" + str(i) for p in policy["profiles"])
    )
    policy["profiles"].append(
        {
            "id": identifier,
            "provider": provider,
            "model": model,
            "capabilities": selected,
            "api_key": key,
            "description": ask("Description (optional): ").strip()[:200],
        }
    )
    validate(policy)
    for role in selected:
        if not policy['routes'].get(role):
            if ask(f'Assign this model to {TASK_NAMES[role]} now? [Y/n]: ').strip().lower() not in {'n', 'no'}:
                policy['routes'][role] = [identifier]
    print('Model added to the draft. Review task assignments before saving.')


def _assign_tasks(policy, ask):
    for step, (role, label) in enumerate(TASK_NAMES.items(), 1):
        eligible = [p for p in policy["profiles"] if role in p["capabilities"]]
        print(f"\nTASK {step}/4 — {label}")
        if not eligible:
            print("No compatible model added. This task remains unconfigured.")
            continue
        previous = policy["routes"].get(role, [])
        for number, p in enumerate(eligible, 1):
            print(f"  {number}. {_profile_label(p)}")
        numbers = {p["id"]: str(i) for i, p in enumerate(eligible, 1)}
        current = ",".join(numbers[i] for i in previous if i in numbers)
        if role == "live":
            print("Choose one model. Live does not switch providers automatically.")
        else:
            print(
                "Choose a primary model, optionally followed by approved alternatives in priority order."
            )
        value = ask(
            f"Model number(s) [{current or 'none'}] (Enter keeps, 0 disables): "
        ).strip()
        if value:
            policy["routes"][role] = (
                []
                if value == "0"
                else [
                    eligible[n - 1]["id"]
                    for n in _numbers(value, len(eligible), multiple=role != "live")
                ]
            )
        ids = policy["routes"].get(role, [])
        allow = role in policy.get("failover", [])
        if role != "live" and len(ids) > 1:
            print(
                "Only these providers may receive this task. Uncertain image requests are never replayed."
            )
            answer = (
                ask(
                    "Use the next approved model after a safe provider failure? ["
                    + ("Y/n" if allow else "y/N")
                    + "]: "
                )
                .strip()
                .lower()
            )
            if answer:
                allow = answer in {"y", "yes"}
        else:
            allow = False
        policy["failover"] = [c for c in policy.get("failover", []) if c != role] + (
            [role] if allow else []
        )
    validate(policy)


def configure():
    from core.setup_config import _safe_input as ask

    settings = load_config()
    active = enabled(settings)
    source = settings["model_routing"] if active else from_legacy(settings)
    policy = json.loads(json.dumps(source))
    while True:
        _show_settings(policy, active)
        try:
            command = ask("Choose an option [1-6]: ").strip()
            if command == "4":
                print("Cancelled. Saved settings were not changed.")
                return False
            if command == "6":
                policy["enabled"] = False
                save(policy)
                print("Standard Text + Live settings restored. Restart Mark to apply.")
                return True
            if command == "3":
                for required in ("text", "live"):
                    if not policy["routes"].get(required):
                        raise ValueError(
                            "Choose a Text and a Live model before saving."
                        )
                save(policy)
                print("Model settings saved. Restart Mark to apply.")
                return True
            draft = json.loads(json.dumps(policy))
            if command == "1":
                _add_profile(draft, settings, ask)
            elif command == "2":
                _assign_tasks(draft, ask)
            elif command == "5":
                number = _numbers(
                    ask("Model number to remove: ").strip(), len(draft["profiles"])
                )[0]
                identifier = draft["profiles"].pop(number - 1)["id"]
                draft["routes"] = {
                    role: [i for i in ids if i != identifier]
                    for role, ids in draft["routes"].items()
                }
            else:
                raise ValueError("Choose an option from 1 to 6.")
            policy = draft
        except (ValueError, RouteUnavailable) as exc:
            print(f"Model settings not changed: {exc}")
        except (EOFError, KeyboardInterrupt, UnicodeDecodeError):
            print("\nCancelled. Saved model settings were not changed.")
            return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true")
    args = parser.parse_args()
    try:
        if args.configure:
            configure()
        else:
            print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
    except (ValueError, RouteUnavailable, EOFError, KeyboardInterrupt):
        print(
            "Model profile operation cancelled or invalid; existing configuration was preserved."
        )
        raise SystemExit(1)
