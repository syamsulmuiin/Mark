"""Explicit response-language preference, separate from observed speech history."""
from __future__ import annotations


def normalize_language(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Language must be a name/code or auto")
    value = value.strip()
    if not value or len(value) > 64 or not all(c.isalpha() or c in ' -_' for c in value):
        raise ValueError("Use a language name/code, for example Indonesian, id-ID, or auto")
    return 'auto' if value.lower() == 'auto' else value


def preferred_language(config=None, memory=None) -> str:
    if config is None:
        from core.setup_config import load_config
        config = load_config()
    selected = config.get('response_language')
    if selected is not None:
        try:
            value = normalize_language(selected)
            return '' if value == 'auto' else value
        except ValueError:
            return ''
    if memory is None:
        from memory.memory_manager import load_memory
        memory = load_memory()
    identity = memory.get('identity', {}) or {}
    entry = identity.get('preferred_response_language', '')
    if isinstance(entry, dict):
        entry = entry.get('value', '')
    try:
        value = normalize_language(entry)
        return '' if value == 'auto' else value
    except ValueError:
        return ''


def language_instruction(config=None, memory=None) -> str:
    language = preferred_language(config, memory)
    if not language:
        return ''
    return (
        f"RESPONSE LANGUAGE POLICY: The user's primary response language is {language}. "
        "Use it for all user-facing answers and spoken acknowledgements. Switch only "
        "when the user explicitly requests another language or a translation; that "
        "exception does not change the saved default. Foreign words, short ambiguous "
        "transcripts, quoted material, logs and tool output do not change this preference. "
        "Preserve code, JSON keys, identifiers and required machine-readable schemas. "
        "Do not infer a new preferred language from detected speech."
    )
