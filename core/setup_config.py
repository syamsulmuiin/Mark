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
    ("openai_codex", "OpenAI / Codex account login (native, no CLI; text only)", True),
    ("anthropic", "Anthropic Claude API (text only)", True),
    ("deepseek", "DeepSeek (text only)", True),
    ("ollama_local", "Ollama (local) (text only)", True),
    ("ollama_cloud", "Ollama (cloud) (text only)", True),
    ("openrouter", "OpenRouter (text only)", True),
    ("google_oauth", "Google Gemini OAuth (own Cloud project; text only)", True),
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


def _resolve_provider_choice(choice: str, default: str, catalog: tuple) -> str:
    """Resolve the exact catalog displayed to the user; numbers are never provider IDs."""
    value = str(choice or default).strip().lower()
    for index, (provider, label, ready) in enumerate(catalog, 1):
        if value in {str(index), provider}:
            if not ready:
                raise ValueError(f"{label} adapter is not implemented; configuration unchanged")
            return provider
    raise ValueError(f"Unknown provider selection. Enter a menu number from 1 to {len(catalog)} or a provider ID; configuration unchanged")


def interactive_llm_setup(*, force_keys: bool = False) -> bool:
    """Finish Text setup before displaying Live choices; save both atomically."""
    from core.model_config import DEFAULT_LIVE_MODEL, DEFAULT_TEXT_MODEL
    current = load_config()
    print("Only the primary configured Text and Live models are used; no automatic fallback.")
    print("\nSTEP 1/2 — TEXT / REASONING PROVIDER")
    for index, (key, label, ready) in enumerate(CHAT_PROVIDER_CATALOG, 1):
        print(f"  {index}. {label}" + ("" if ready else " [not implemented]"))
    try:
        provider_default = str(next((i for i, (key, _, _) in enumerate(CHAT_PROVIDER_CATALOG, 1)
                                     if key == current.get("llm_provider", "gemini")), 1))
        provider_choice = _safe_input(f"Chat / reasoning provider [{provider_default}]: ").strip().lower()
        provider = _resolve_provider_choice(provider_choice, provider_default, CHAT_PROVIDER_CATALOG)
        api_key = None
        if provider == "openai_codex":
            from core.llm_codex import check_login, login, login_browser
            from core import provider_credentials
            record = provider_credentials.load("openai_codex")
            if force_keys or not record.get("access_token") or record.get("invalid"):
                method = _safe_input("OpenAI account login: 1. Device code  2. Browser PKCE [1]: ").strip() or "1"
                if method == "1":
                    login()
                elif method == "2":
                    login_browser(getpass.getpass)
                else:
                    raise ValueError("Invalid OpenAI login method; configuration unchanged")
            check_login()
        if provider == "google_oauth":
            from core.llm_google_oauth import login, credentials
            from core import provider_credentials
            record = provider_credentials.load("google_oauth")
            if force_keys or not record.get("credentials") or record.get("invalid"):
                login(_safe_input, getpass.getpass)
            credentials()
        if provider == "openrouter" and (force_keys or not current.get("openrouter_api_key")):
            method = _safe_input("OpenRouter authentication: 1. API key  2. Browser login [1]: ").strip() or "1"
            if method == "2":
                from core.provider_oauth import openrouter_login
                api_key = openrouter_login(getpass.getpass)
            elif method != "1":
                raise ValueError("Invalid OpenRouter authentication method")
        if provider == "anthropic":
            print("Claude API connects directly without Claude Code. Claude.ai subscription login is not offered by this app; use your Anthropic API key.")
        if api_key is None and provider not in {"ollama_local", "openai_codex", "google_oauth"} and (force_keys or not current.get(f"{provider}_api_key")):
            api_key = getpass.getpass(f"{provider} text API key: ").strip()
            if not api_key:
                print("Text API key required; configuration unchanged.")
                return False
        choices = {}
        if provider == "gemini":
            default = str(current.get("text_models") or DEFAULT_TEXT_MODEL).split(",")[0].strip()
            choices["text_models"] = _safe_input(f"Text model [{default}]: ").strip() or default
        else:
            saved_model = (current.get("provider_models") or {}).get(provider, "")
            if not saved_model and current.get("llm_provider") == provider:
                saved_model = current.get("chat_models") or ""
            saved_model = str(saved_model).split(",")[0].strip()
            model = _safe_input(f"{provider} text model ID [{saved_model or 'required'}]: ").strip() or saved_model
            if not model:
                print("Text model ID required; configuration unchanged.")
                return False
            choices["chat_models"] = model

        print("\nSTEP 2/2 — LIVE / VOICE PROVIDER")
        for index, (key, label, ready) in enumerate(LIVE_PROVIDER_CATALOG, 1):
            print(f"  {index}. {label}" + ("" if ready else " [not implemented]"))
        live_default_choice = str(next((i for i, (key, _, _) in enumerate(LIVE_PROVIDER_CATALOG, 1)
                                       if key == current.get("live_provider", "gemini")), 1))
        live_choice = _safe_input(f"Live / voice provider [{live_default_choice}]: ").strip().lower()
        live_provider = _resolve_provider_choice(live_choice, live_default_choice, LIVE_PROVIDER_CATALOG)
        choices["live_provider"] = live_provider
        live_key_field = "openai_api_key" if live_provider == "openai_realtime" else "gemini_api_key"
        if force_keys or not current.get(live_key_field):
            same_key_provider = "openai" if live_provider == "openai_realtime" else "gemini"
            live_key = api_key if provider == same_key_provider and api_key else getpass.getpass(f"{live_provider} voice API key: ").strip()
            if not live_key:
                print("Live API key required; configuration unchanged.")
                return False
            choices["live_api_key"] = live_key
        if live_provider == "gemini":
            default = str(current.get("live_models") or DEFAULT_LIVE_MODEL).split(",")[0].strip()
            choices["live_models"] = _safe_input(f"Live audio model [{default}]: ").strip() or default
        else:
            default = current.get("realtime_model") or "gpt-realtime-2.1"
            choices["realtime_model"] = _safe_input(f"OpenAI Realtime model [{default}]: ").strip() or default
        save_llm_selection(provider, "hybrid", provider_api_key=api_key, **choices)
    except (RuntimeError, ValueError) as exc:
        print(f"LLM setup failed: {exc}")
        print(f"Setup module: {Path(__file__).resolve()}")
        return False
    except (EOFError, KeyboardInterrupt, UnicodeDecodeError):
        print("LLM selection cancelled; existing configuration preserved.")
        return False
    print(f"Hybrid configuration saved ({provider} text + {live_provider} voice).")
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
