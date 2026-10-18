"""Shared first-run configuration for UI, CLI and background runtimes."""
from __future__ import annotations
import getpass, json, os, platform
from pathlib import Path
from core.network_config import LOCAL_BASE_URL

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "api_keys.json"

def load_config() -> dict:
    try: return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception: return {}

def save_response_language(language: str) -> dict:
    from core.response_language import normalize_language
    value = normalize_language(language)
    current = load_config()
    current["response_language"] = value
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    try: os.chmod(CONFIG_FILE, 0o600)
    except Exception: pass
    return current


def interactive_language_setup() -> bool:
    current = load_config().get("response_language", "auto")
    print("Response language: use a primary language to prevent accidental switching.")
    try:
        value = _safe_input(f"Primary response language (ID / EN / other code or name; auto follows user) [{current}]: ").strip()
        if value:
            save_response_language(value)
        return True
    except (EOFError, KeyboardInterrupt, UnicodeDecodeError):
        print("Language selection cancelled; existing preference preserved.")
        return False
    except ValueError as exc:
        print(f"Language selection failed: {exc}")
        return False


def configured() -> bool:
    d = load_config()
    live = d.get("live_provider") or "gemini"
    key_field = "openai_api_key" if live == "openai_realtime" else "gemini_api_key"
    return (live in {"gemini", "openai_realtime"}
            and bool(str(d.get(key_field) or "").strip())
            and bool(str(d.get("os_system") or "").strip())
            and (d.get("llm_provider", "gemini") != "gemini" or bool(d.get("gemini_api_key"))))

def save_config(gemini_api_key: str, os_system: str | None=None) -> dict:
    key=str(gemini_api_key or "").strip()
    if not key: raise ValueError("Gemini API key cannot be empty")
    current=load_config(); current["gemini_api_key"]=key
    current["os_system"]=(os_system or platform.system()).strip() or platform.system()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp=CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    try: os.chmod(CONFIG_FILE, 0o600)
    except Exception: pass
    return current

# Provider catalog is separate from implemented adapters. Never route an
# unsupported provider to Gemini silently: that would leak prompts/credentials
# to a different provider than the user selected.
CHAT_PROVIDER_CATALOG = (
    ("gemini", "Google Gemini", True),
    ("openai", "OpenAI API (text only)", True),
    ("openai_codex", "OpenAI Codex CLI (existing account login, text only)", True),
    ("anthropic", "Anthropic Claude API (text only)", True),
    ("deepseek", "DeepSeek (text only)", True),
    ("ollama_local", "Ollama (local) (text only)", True),
    ("ollama_cloud", "Ollama (cloud) (text only)", True),
    ("openrouter", "OpenRouter (text only)", True),
)
LIVE_PROVIDER_CATALOG = (
    ("gemini", "Gemini Live", True),
    ("openai_realtime", "OpenAI Realtime", True),
)
SUPPORTED_PROVIDERS = tuple(key for key, _, ready in CHAT_PROVIDER_CATALOG if ready)
SUPPORTED_MODES = ("hybrid",)


def save_llm_selection(provider: str = "gemini", mode: str = "hybrid",
                       live_models: str | None = None,
                       text_models: str | None = None,
                       provider_api_key: str | None = None,
                       chat_models: str | None = None,
                       live_provider: str | None = None,
                       live_api_key: str | None = None,
                       realtime_model: str | None = None) -> dict:
    """Persist provider selection without touching the existing API key.

    Text providers are independent of the Gemini voice transport.
    Keep model selections per provider so switching cannot reuse another API's model.
    """
    provider = str(provider).strip().lower()
    mode = str(mode).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported LLM mode: {mode}")
    current = load_config()
    previous_provider = current.get("llm_provider", "gemini")
    previous_chat = current.get("chat_models")
    model_selections = dict(current.get("provider_models") or {})
    if previous_chat:
        model_selections.setdefault(previous_provider, previous_chat)
    current["llm_provider"] = provider
    current["llm_mode"] = mode
    current.setdefault("os_system", platform.system())
    if provider_api_key is not None:
        current[f"{provider}_api_key"] = provider_api_key.strip()
    for field, value in (("live_models", live_models), ("text_models", text_models), ("chat_models", chat_models)):
        if value is not None:
            models = list(dict.fromkeys(x.strip() for x in value.split(",") if x.strip()))
            if not models:
                raise ValueError(f"{field} must contain at least one model")
            current[field] = ",".join(models)
    if chat_models is not None:
        model_selections[provider] = current["chat_models"]
    elif provider in model_selections:
        current["chat_models"] = model_selections[provider]
    elif previous_provider != provider:
        current.pop("chat_models", None)
    current["provider_models"] = model_selections
    selected_live = live_provider or current.get("live_provider") or "gemini"
    if selected_live not in {"gemini", "openai_realtime"}:
        raise ValueError(f"Unsupported Live provider: {selected_live}")
    current["live_provider"] = selected_live
    if live_api_key is not None:
        current["openai_api_key" if selected_live == "openai_realtime" else "gemini_api_key"] = live_api_key.strip()
    if realtime_model is not None:
        if not realtime_model.strip():
            raise ValueError("Realtime model is required")
        current["realtime_model"] = realtime_model.strip()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    try: os.chmod(CONFIG_FILE, 0o600)
    except Exception: pass
    return current


def _safe_input(prompt: str) -> str:
    """Decode malformed terminal input without terminating setup."""
    import sys
    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(errors="replace")
        except (OSError, ValueError, TypeError):
            pass
    return input(prompt)


def interactive_llm_setup(*, force_keys: bool = False) -> bool:
    """Configure supported LLM provider and separate Live/text model ladders."""
    from core.model_config import (
        DEFAULT_LIVE_MODEL, DEFAULT_LIVE_FALLBACK_MODEL,
        DEFAULT_TEXT_MODEL, DEFAULT_TEXT_FALLBACK_MODEL,
    )
    current = load_config()
    print("\nCHAT / REASONING PROVIDER")
    print("Only the primary configured Text and Live models are used; no automatic fallback.")
    for index, (key, label, ready) in enumerate(CHAT_PROVIDER_CATALOG, 1):
        print(f"  {index}. {label}" + ("" if ready else " [not implemented; installing a package will not enable it]"))
    print("\nLIVE / VOICE PROVIDER")
    for index, (key, label, ready) in enumerate(LIVE_PROVIDER_CATALOG, 1):
        print(f"  {index}. {label}" + ("" if ready else " [not implemented; installing a package will not enable it]"))
    print("Hybrid: typed chat and text reasoning use the selected provider; voice uses the selected Live provider.")
    try:
        provider_default = str(next((i for i, (key, _, _) in enumerate(CHAT_PROVIDER_CATALOG, 1)
                                     if key == current.get("llm_provider", "gemini")), 1))
        live_default_choice = str(next((i for i, (key, _, _) in enumerate(LIVE_PROVIDER_CATALOG, 1)
                                       if key == current.get("live_provider", "gemini")), 1))
        provider_choice = _safe_input(f"Chat / reasoning provider [{provider_default}]: ").strip().lower()
        live_choice = _safe_input(f"Live / voice provider [{live_default_choice}]: ").strip().lower()
        provider_choices = {str(i): key for i, (key, _, _) in enumerate(CHAT_PROVIDER_CATALOG, 1)}
        live_choices = {str(i): key for i, (key, _, _) in enumerate(LIVE_PROVIDER_CATALOG, 1)}
        provider = provider_choices.get(provider_choice or provider_default, provider_choice)
        live_provider = live_choices.get(live_choice or live_default_choice, live_choice)
        if provider not in SUPPORTED_PROVIDERS:
            print(f"{provider!r} is listed for planning but its chat/tool adapter is not implemented.")
            return False
        if live_provider not in {"gemini", "openai_realtime"}:
            print(f"{live_provider!r} Live audio transport is not implemented.")
            return False
        print(f"Mode: Hybrid ({live_provider} voice + {provider} text reasoning)")
        api_key = None
        if provider != "gemini":
            print("Text generation only: Gemini-specific tool and multimodal helpers remain on Gemini.")
            if provider == "openai_codex":
                from core.llm_codex import check_login
                check_login()
            if provider not in {"ollama_local", "openai_codex"} and (force_keys or not current.get(f"{provider}_api_key")):
                api_key = getpass.getpass(f"{provider} API key: ").strip()
                if not api_key:
                    print("API key required; configuration unchanged.")
                    return False
        if provider == "gemini" and (force_keys or not current.get("gemini_api_key")):
            api_key = getpass.getpass("Gemini text API key: ").strip()
            if not api_key:
                print("Gemini text API key required; configuration unchanged.")
                return False
        choices = {"live_provider": live_provider}
        live_key_field = "openai_api_key" if live_provider == "openai_realtime" else "gemini_api_key"
        if force_keys or not current.get(live_key_field):
            same_key_provider = "openai" if live_provider == "openai_realtime" else "gemini"
            live_key = api_key if provider == same_key_provider and api_key else getpass.getpass(f"{live_provider} voice API key: ").strip()
            if not live_key:
                print("Live API key required; configuration unchanged.")
                return False
            choices["live_api_key"] = live_key
        if provider != "gemini":
            saved_model = (current.get("provider_models") or {}).get(provider, "")
            if not saved_model and current.get("llm_provider") == provider:
                saved_model = current.get("chat_models") or ""
            model = _safe_input(f"{provider} text model ID [{saved_model or 'required'}]: ").strip() or saved_model
            if not model:
                print("Text model ID required; configuration unchanged.")
                return False
            choices["chat_models"] = model
            if live_provider == "gemini":
                live_default = current.get("live_models") or f"{DEFAULT_LIVE_MODEL},{DEFAULT_LIVE_FALLBACK_MODEL}"
                choices["live_models"] = _safe_input(f"Live audio models [{live_default}]: ").strip() or live_default
        else:
            defaults = (
                ("live_models", "Live audio", f"{DEFAULT_LIVE_MODEL},{DEFAULT_LIVE_FALLBACK_MODEL}"),
                ("text_models", "Text / tools", f"{DEFAULT_TEXT_MODEL},{DEFAULT_TEXT_FALLBACK_MODEL}"),
            )
            for field, label, default in defaults:
                if field == "live_models" and live_provider != "gemini":
                    continue
                value = _safe_input(f"{label} models [{current.get(field) or default}]: ").strip()
                choices[field] = value or current.get(field) or default
        if live_provider == "openai_realtime":
            realtime_default = current.get("realtime_model") or "gpt-realtime-2.1"
            choices["realtime_model"] = _safe_input(f"OpenAI Realtime model [{realtime_default}]: ").strip() or realtime_default
        save_llm_selection(provider, "hybrid", provider_api_key=api_key, **choices)
    except RuntimeError as exc:
        print(f"LLM setup failed: {exc}")
        return False
    except (EOFError, KeyboardInterrupt, UnicodeDecodeError):
        print("LLM selection cancelled; existing configuration preserved.")
        return False
    print(f"Hybrid configuration saved ({live_provider} voice + {provider} text).")
    return True


def interactive_setup(force: bool=False) -> bool:
    if configured() and not force: return True
    print("\nMARK FIRST-RUN SETUP")
    print("Select text and voice providers. Keys are stored in git-ignored config/api_keys.json.")
    if not interactive_llm_setup(force_keys=force):
        return False
    if not interactive_language_setup():
        return False
    print("\nRemote access lets paired devices reach JARVIS outside your home/LAN.")
    try: remote=_safe_input("Enable Cloudflare remote access? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt, UnicodeDecodeError): remote="n"
    if remote not in ("n","no"):
        try:
            from core.cloudflare_tunnel import install, configure_named_tunnel, DEFAULT_HOSTNAME
            install()
            print(f"Permanent endpoint: https://{DEFAULT_HOSTNAME}")
            print(f"Create a remotely-managed Cloudflare Tunnel and map that hostname to {LOCAL_BASE_URL}.")
            token=getpass.getpass("Cloudflare Tunnel token: ").strip()
            if not token: raise ValueError("Tunnel token was empty")
            configure_named_tunnel(token, DEFAULT_HOSTNAME, True)
            print(f"Cloudflare Named Tunnel enabled at https://{DEFAULT_HOSTNAME}.")
        except Exception as e:
            print(f"Cloudflare setup failed: {e}. LAN pairing remains available.")
    print("Setup complete.")
    return True
