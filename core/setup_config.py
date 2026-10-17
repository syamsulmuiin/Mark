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

def configured() -> bool:
    d=load_config(); return bool(str(d.get("gemini_api_key") or "").strip()) and bool(str(d.get("os_system") or "").strip())

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
    ("openai_codex", "OpenAI Codex (account authorization)", False),
    ("anthropic", "Anthropic Claude", False),
    ("deepseek", "DeepSeek (text only)", True),
    ("ollama_local", "Ollama (local) (text only)", True),
    ("ollama_cloud", "Ollama (cloud) (text only)", True),
    ("openrouter", "OpenRouter (text only)", True),
)
LIVE_PROVIDER_CATALOG = (
    ("gemini", "Gemini Live", True),
    ("openai_realtime", "OpenAI Realtime", False),
)
SUPPORTED_PROVIDERS = tuple(key for key, _, ready in CHAT_PROVIDER_CATALOG if ready)
SUPPORTED_MODES = ("hybrid",)


def save_llm_selection(provider: str = "gemini", mode: str = "hybrid",
                       live_models: str | None = None,
                       text_models: str | None = None,
                       provider_api_key: str | None = None,
                       chat_models: str | None = None) -> dict:
    """Persist provider selection without touching the existing API key.

    Only Gemini hybrid is wired into the current runtime. Fail closed rather
    than offering providers whose text/Live clients do not exist yet.
    """
    provider = str(provider).strip().lower()
    mode = str(mode).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported LLM mode: {mode}")
    current = load_config()
    current["llm_provider"] = provider
    current["llm_mode"] = mode
    if provider_api_key is not None and provider != "gemini":
        current[f"{provider}_api_key"] = provider_api_key.strip()
    for field, value in (("live_models", live_models), ("text_models", text_models), ("chat_models", chat_models)):
        if value is not None:
            models = list(dict.fromkeys(x.strip() for x in value.split(",") if x.strip()))
            if not models:
                raise ValueError(f"{field} must contain at least one model")
            current[field] = ",".join(models)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    try: os.chmod(CONFIG_FILE, 0o600)
    except Exception: pass
    return current


def interactive_llm_setup() -> bool:
    """Configure supported LLM provider and separate Live/text model ladders."""
    from core.model_config import (
        DEFAULT_LIVE_MODEL, DEFAULT_LIVE_FALLBACK_MODEL,
        DEFAULT_TEXT_MODEL, DEFAULT_TEXT_FALLBACK_MODEL,
    )
    current = load_config()
    print("\nCHAT / EXECUTION PROVIDER")
    for index, (key, label, ready) in enumerate(CHAT_PROVIDER_CATALOG, 1):
        print(f"  {index}. {label}" + ("" if ready else " [adapter not installed]"))
    print("\nLIVE / VOICE PROVIDER")
    for index, (key, label, ready) in enumerate(LIVE_PROVIDER_CATALOG, 1):
        print(f"  {index}. {label}" + ("" if ready else " [adapter not installed]"))
    print("Hybrid uses the selected provider for routed plain text; Live/tools remain Gemini.")
    try:
        provider_choice = input("Chat / execution provider [1]: ").strip().lower()
        live_choice = input("Live / voice provider [1]: ").strip().lower()
        provider_choices = {str(i): key for i, (key, _, _) in enumerate(CHAT_PROVIDER_CATALOG, 1)}
        live_choices = {str(i): key for i, (key, _, _) in enumerate(LIVE_PROVIDER_CATALOG, 1)}
        provider = provider_choices.get(provider_choice or "1", provider_choice)
        live_provider = live_choices.get(live_choice or "1", live_choice)
        if provider not in SUPPORTED_PROVIDERS:
            print(f"{provider!r} is listed for planning but its chat/tool adapter is not implemented.")
            return False
        if live_provider != "gemini":
            print(f"{live_provider!r} Live audio transport is not implemented.")
            return False
        print("Mode: Hybrid (Gemini Live voice + selected text provider)")
        api_key = None
        if provider != "gemini":
            print("Text generation only: Gemini-specific tool and multimodal helpers remain on Gemini.")
            if provider != "ollama_local" and not current.get(f"{provider}_api_key"):
                api_key = getpass.getpass(f"{provider} API key: ").strip()
                if not api_key:
                    print("API key required; configuration unchanged.")
                    return False
        print("Live models must support the Gemini Live audio API.")
        choices = {}
        if provider != "gemini":
            model = input(f"{provider} text model ID (required): ").strip()
            if not model:
                print("Text model ID required; configuration unchanged.")
                return False
            choices["chat_models"] = model
            live_default = current.get("live_models") or f"{DEFAULT_LIVE_MODEL},{DEFAULT_LIVE_FALLBACK_MODEL}"
            choices["live_models"] = input(f"Live audio models [{live_default}]: ").strip() or live_default
        else:
            defaults = (
                ("live_models", "Live audio", f"{DEFAULT_LIVE_MODEL},{DEFAULT_LIVE_FALLBACK_MODEL}"),
                ("text_models", "Text / tools", f"{DEFAULT_TEXT_MODEL},{DEFAULT_TEXT_FALLBACK_MODEL}"),
            )
            for field, label, default in defaults:
                value = input(f"{label} models [{current.get(field) or default}]: ").strip()
                choices[field] = value or current.get(field) or default
        save_llm_selection(provider, "hybrid", provider_api_key=api_key, **choices)
    except (EOFError, KeyboardInterrupt):
        print("LLM selection cancelled; existing configuration preserved.")
        return False
    print("Hybrid configuration saved (Gemini Live + selected text provider).")
    return True


def interactive_setup(force: bool=False) -> bool:
    if configured() and not force: return True
    print("\\nJARVIS FIRST-RUN SETUP")
    print("Gemini API key is stored locally in config/api_keys.json and is git-ignored.")
    try: key=getpass.getpass("Gemini API key: ").strip()
    except (EOFError, KeyboardInterrupt): return False
    if not key:
        print("Setup cancelled: API key was empty."); return False
    save_config(key, platform.system())
    if not interactive_llm_setup():
        return False
    print("\nRemote access lets paired devices reach JARVIS outside your home/LAN.")
    try: remote=input("Enable Cloudflare remote access? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt): remote="n"
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
