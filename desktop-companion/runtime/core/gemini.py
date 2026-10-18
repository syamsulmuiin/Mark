"""Compatibility boundary: desktop companions execute tools, never select an LLM.

Natural-language reasoning belongs to the server's selected Text provider. A
legacy action requiring local model inference must return that limitation rather
than creating an unconfigured Gemini/Live client on the companion machine.
"""
FAST, SMART, SEARCH, LIVE = "fast", "smart", "search", "live"


def call(*args, **kwargs):
    raise RuntimeError("Local companion LLM calls are disabled. Resolve this operation with the server Text provider, then send explicit device arguments.")


def text(*args, **kwargs):
    return call(*args, **kwargs)


def as_json(*args, **kwargs):
    return call(*args, **kwargs)


def client(*args, **kwargs):
    return call(*args, **kwargs)
