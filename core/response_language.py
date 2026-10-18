"""Explicit response-language preference, separate from observed speech history."""
from __future__ import annotations


LANGUAGE_NAMES = {
    "ID": "Indonesian", "EN": "English", "JA": "Japanese",
    "KO": "Korean", "ZH": "Chinese", "AR": "Arabic",
    "ES": "Spanish", "FR": "French", "DE": "German",
    "PT": "Portuguese", "RU": "Russian", "HI": "Hindi",
    "MS": "Malay", "TH": "Thai", "VI": "Vietnamese",
    "TR": "Turkish", "IT": "Italian", "NL": "Dutch",
}

def normalize_language(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Language must be a name/code or auto")
    value = value.strip()
    if not value or len(value) > 64 or not all(c.isalpha() or c in ' -_' for c in value):
        raise ValueError("Use a language name/code, for example ID, EN, id-ID, or auto")
    if value.lower() == 'auto':
        return 'auto'
    if len(value) == 2 and value.isascii():
        return value.upper()
    return value


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


LANGUAGE_LOCALES = {
    'ID': 'id-ID', 'EN': 'en-US', 'JA': 'ja-JP', 'KO': 'ko-KR',
    'ZH': 'zh-CN', 'AR': 'ar-EG', 'ES': 'es-ES', 'FR': 'fr-FR',
    'DE': 'de-DE', 'PT': 'pt-BR', 'RU': 'ru-RU', 'HI': 'hi-IN',
    'MS': 'ms-MY', 'TH': 'th-TH', 'VI': 'vi-VN', 'TR': 'tr-TR',
    'IT': 'it-IT', 'NL': 'nl-NL',
}


def input_language_codes(config=None, memory=None) -> list[str]:
    """Use a recognized primary language as an ASR hint, not a language lock."""
    import re
    language = preferred_language(config, memory)
    if not language:
        return []
    aliases = {name.casefold(): code for code, name in LANGUAGE_NAMES.items()}
    aliases.update({'bahasa indonesia': 'ID', 'indonesia': 'ID'})
    language = aliases.get(language.casefold(), language).replace('_', '-')
    if language.upper() in LANGUAGE_LOCALES:
        return [LANGUAGE_LOCALES[language.upper()]]
    if re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', language):
        parts = language.split('-')
        return ['-'.join([parts[0].lower()] + [
            part.title() if len(part) == 4 else part.upper() for part in parts[1:]])]
    # Unknown display names remain usable for response instructions; do not send
    # them as invalid BCP-47 strings to a provider.
    return []


def language_instruction(config=None, memory=None) -> str:
    language = preferred_language(config, memory)
    if not language:
        return ''
    language = LANGUAGE_NAMES.get(language, language)
    return (
        f"RESPONSE LANGUAGE POLICY: The user's primary response language is {language}. "
        "Use it for all user-facing answers and spoken acknowledgements. Switch only "
        "when the user explicitly requests another language or a translation; that "
        "exception does not change the saved default. Foreign words, short ambiguous "
        "transcripts, quoted material, logs and tool output do not change this preference. "
        "Preserve code, JSON keys, identifiers and required machine-readable schemas. "
        "Do not infer a new preferred language from detected speech."
    )
