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


def configure():
    settings = load_config()
    policy = settings["model_routing"] if enabled(settings) else from_legacy(settings)
    # Work on a copy; cancellation never partially changes live configuration.
    policy = json.loads(json.dumps(policy))
    print(
        "Unified model profiles. Capabilities describe adapter support, not guaranteed model entitlement."
    )
    print(
        "Text / image reading / image generation / Live are implemented. Video and music generation are unavailable."
    )
    while True:
        for p in policy["profiles"]:
            print(
                f"{p['id']}: {p['provider']} / {p['model']} — {', '.join(p['capabilities'])}; {p.get('description', '')}"
            )
        command = input(
            "1 Add model  2 Assign task routes  3 Save and exit  4 Cancel  5 Remove profile  6 Use legacy selections: "
        ).strip()
        if command == "4":
            return
        if command == "6":
            policy["enabled"] = False
            save(policy)
            print("Legacy primary selections restored. Restart Mark.")
            return
        if command == "1":
            identifier = input("Profile ID (snake_case): ").strip()
            for provider, caps in ADAPTERS.items():
                print(provider + ": " + ", ".join(sorted(caps)))
            provider = input("Provider: ").strip()
            if provider not in ADAPTERS:
                raise ValueError("Unsupported provider")
            caps = (
                input("Capabilities, comma-separated from provider description: ")
                .strip()
                .split(",")
            )
            caps = [c.strip() for c in caps if c.strip()]
            key = (
                ""
                if provider in {"openai_codex", "google_oauth", "ollama_local"}
                else getpass.getpass("API key: ").strip()
            )
            models = discover_models(provider, key, caps)
            for number, name in enumerate(models, 1):
                print(f"{number}. {name}")
            value = input("Model number or exact model ID: ").strip()
            model = (
                models[int(value) - 1]
                if value.isdigit() and 1 <= int(value) <= len(models)
                else value
            )
            policy["profiles"].append(
                {
                    "id": identifier,
                    "provider": provider,
                    "model": model,
                    "capabilities": caps,
                    "api_key": key,
                    "description": input("Short description: ").strip()[:200],
                }
            )
            validate(policy)
        elif command == "5":
            identifier = input("Profile ID to remove: ").strip()
            policy["profiles"] = [
                p for p in policy["profiles"] if p["id"] != identifier
            ]
            policy["routes"] = {
                c: [i for i in ids if i != identifier]
                for c, ids in policy["routes"].items()
            }
        elif command == "2":
            for role, label in CAPABILITIES.items():
                print(
                    label
                    + ": "
                    + ", ".join(
                        p["id"] for p in policy["profiles"] if role in p["capabilities"]
                    )
                )
                previous = policy["routes"].get(role, [])
                value = input(
                    f"Approved profile IDs in priority order [{','.join(previous)}] (blank keeps, - clears): "
                ).strip()
                if value:
                    policy["routes"][role] = (
                        [] if value == "-" else [v.strip() for v in value.split(",")]
                    )
                if role != "live":
                    allow = (
                        input("Allow next approved profile on safe failures? [y/N]: ")
                        .strip()
                        .lower()
                        == "y"
                    )
                    policy["failover"] = [
                        c for c in policy.get("failover", []) if c != role
                    ] + ([role] if allow else [])
            validate(policy)
        elif command == "3":
            save(policy)
            print("Profiles saved. Restart Mark to apply Live changes.")
            return
        else:
            raise ValueError("Invalid menu choice")


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
