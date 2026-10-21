#web_search.py
import json
import sys
import threading
import time
from pathlib import Path

# ── Gemini grounding quota circuit breaker ────────────────────────────────────
# The google_search grounding tool has its own small quota, separate from plain
# generation.  Once it is spent every call returns 429 — so retrying it at the
# top of every search only adds a dead round-trip before the DDG fallback runs.
# After a quota error, skip Gemini entirely for a cooldown period.
_QUOTA_COOLDOWN_SEC  = 900          # 15 minutes
_quota_blocked_until = 0.0
_quota_lock          = threading.Lock()

# Short circuit repeated DuckDuckGo transport failures such as TLS handshake
# errors. One concise diagnostic is enough; retries within the same outage only
# create warning spam and latency.
_DDG_FAILURE_COOLDOWN_SEC = 300
_ddg_blocked_until = 0.0
_ddg_lock = threading.Lock()


def _gemini_available() -> bool:
    from core.setup_config import load_config
    if str(load_config().get("llm_provider") or "gemini").lower() != "gemini":
        return False
    with _quota_lock:
        return time.monotonic() >= _quota_blocked_until


def _note_gemini_error(exc: Exception) -> None:
    """Trip the breaker when the error is a quota / rate-limit rejection."""
    global _quota_blocked_until
    msg = str(exc)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        with _quota_lock:
            already = time.monotonic() < _quota_blocked_until
            _quota_blocked_until = time.monotonic() + _QUOTA_COOLDOWN_SEC
        if not already:
            print(
                "[WebSearch] Gemini grounding quota exhausted — skipping it for "
                f"{_QUOTA_COOLDOWN_SEC // 60} min and serving results from DDG."
            )


class _QuotaCooldown(RuntimeError):
    """Raised instead of calling Gemini while the quota breaker is open."""


def _log_gemini_failure(context: str, exc: Exception) -> None:
    """Log a Gemini failure — silently when it is just the expected cooldown."""
    if isinstance(exc, _QuotaCooldown):
        return          # announced once when the breaker tripped; not a warning
    print(f"[WebSearch] \u26a0\ufe0f {context} failed ({exc}) — using DDG instead")


def _run_bounded(fn, timeout: float, label: str = "task"):
    """Run fn() in a daemon thread; return its result, or None if it overruns."""
    box = [None]

    def _run():
        try:
            box[0] = fn()
        except Exception as e:
            _log_gemini_failure(label, e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print(f"[WebSearch] {label} exceeded {timeout:.0f}s — moving on")
    return box[0]

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _gemini_search(query: str) -> str:
    if not _gemini_available():
        raise _QuotaCooldown("Gemini grounding is not the selected Text provider or is in cooldown")

    from core import gemini

    # Grounded search reads a live page, so it gets a longer deadline than the
    # default. Execution remains on the configured primary Text model.
    try:
        response = gemini.call(query, tier=gemini.SEARCH,
                               config={"tools": [{"google_search": {}}]},
                               timeout_ms=30_000)
        if response is None:
            errors = gemini.last_call_errors()
            detail = "; ".join(f"{model}: {message}" for model, message in errors)
            raise RuntimeError(detail or "the configured primary Text model returned no search response")
    except Exception as e:
        _note_gemini_error(e)
        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            raise _QuotaCooldown(str(e)) from None
        raise

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _get_ddgs():
    """
    Returns the DDGS class.  The package was renamed duckduckgo-search -> ddgs;
    the legacy package's endpoints are now rejected by DuckDuckGo (news() gets a
    403 Ratelimit, text() silently returns zero results), so warn loudly if we
    end up on it instead of failing in silence.
    """
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS
        print(
            "[WebSearch] ⚠️ Using the deprecated 'duckduckgo-search' package — "
            "DuckDuckGo blocks its endpoints, so every search will come back "
            "empty.  Fix with:  pip install -U ddgs"
        )
        return DDGS


def _ddg_available() -> bool:
    with _ddg_lock:
        return time.monotonic() >= _ddg_blocked_until


def _note_ddg_failure(exc: Exception) -> None:
    global _ddg_blocked_until
    with _ddg_lock:
        already = time.monotonic() < _ddg_blocked_until
        _ddg_blocked_until = time.monotonic() + _DDG_FAILURE_COOLDOWN_SEC
    if not already:
        print(
            "[WebSearch] DDG transport unavailable — skipping it for "
            f"{_DDG_FAILURE_COOLDOWN_SEC // 60} min ({type(exc).__name__})."
        )


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    if not _ddg_available():
        return []
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("href",   ""),
                })
    except Exception as e:
        # DDGS can route text searches through multiple backends. A failed
        # default transport should not disable search before trying another.
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results, backend="bing"):
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url": r.get("href", ""),
                    })
        except Exception as fallback_error:
            _note_ddg_failure(fallback_error)
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    if not _ddg_available():
        return []
    DDGS = _get_ddgs()
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        _note_ddg_failure(e)
    # Also covers the legacy-package case, where news() returns an empty list
    # instead of raising.
    if not results:
        results = _ddg_search(query, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    if not _gemini_available():
        rows = _ddg_news("world news today", max_results=n)
        return [str(row.get("title") or "") for row in rows], _format_news("world news today", rows)
    from core import gemini

    response = gemini.call(
        f"Current world news: {n} headlines. Numbered list, titles only.",
        tier=gemini.SEARCH,
        config={"tools": [{"google_search": {}}]},
        timeout_ms=30_000,
    )
    if response is None:
        return [], ""

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini search", e)
        results = _ddg_search(query)
        return _format_ddg(query, results)


def _news(query: str) -> str:
    """
    DDG first, Gemini as backup.

    The old version raced both backends in parallel and kept the first answer.
    That burned one google_search grounding call on *every* news request —
    including the startup briefing — even when DDG had already won the race.
    Grounding has a small quota, so it ran dry after a handful of launches and
    then 429'd for everything else (research/compare), which are the modes that
    actually need a synthesised answer.

    DDG news returns in well under a second and gives raw headlines, which is
    exactly what the briefing wants, so it goes first and Gemini is only touched
    when DDG comes back empty.
    """
    gemini_query = f"latest news today: {query}" if query else "top world news today"
    ddg_query    = query if query else "world news today"

    def _ddg_attempt() -> str:
        return _format_news(ddg_query, _ddg_news(ddg_query, max_results=8))

    text = _run_bounded(_ddg_attempt, timeout=5.0, label="DDG news")
    if text and len(text) > 60 and not text.startswith("No news found"):
        return text

    text = _run_bounded(
        lambda: _gemini_search(gemini_query), timeout=6.0, label="Gemini news"
    )
    if text and len(text) > 60:
        return text

    return f"No news found for: {query}"


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        _log_gemini_failure("Gemini research", e)
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        _log_gemini_failure("Gemini price", e)
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        _log_gemini_failure("Gemini compare", e)

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def _images(query: str, delivery: str = "attachments", count: int = 6) -> str:
    from urllib.parse import urlsplit
    import hashlib
    import time
    from core.image_review import review_images, preview, log_review
    from core.llm_visual import visual_provider, VisualReviewUnavailable
    if type(count) is not int or not 1 <= count <= 20:
        return json.dumps({"status":"FAILED", "reason":"invalid_image_count",
                           "instruction":"Choose 1-20 images per request. Split larger requests explicitly; no images were searched or silently truncated."})
    if delivery != "links":
        try:
            visual_provider()
        except VisualReviewUnavailable:
            return json.dumps({'status':'BLOCKED','verified':False,'reason':'visual_review_unavailable',
                'instruction':'The configured Text provider has no image-input adapter. No model fallback or unreviewed image delivery was performed. Explain the limitation; do not claim the image request was completed.'})
    if not _ddg_available():
        return json.dumps({"status":"FAILED", "reason":"image_search_transport_cooldown", "results":[]})
    deadline = time.monotonic() + 90
    limit = count if delivery == "links" else min(60, max(12, count * 3))
    try:
        with _get_ddgs()(timeout=8) as engine:
            rows = engine.images(query, max_results=limit, safesearch="moderate")
        results, seen_urls = [], set()
        for row in rows:
            image, page = str(row.get("image") or ""), str(row.get("url") or "")
            if urlsplit(image).scheme not in {"http","https"} or image in seen_urls:
                continue
            seen_urls.add(image)
            results.append({'title':str(row.get('title') or '')[:500], 'image_url':image,
                            'source_url':page if urlsplit(page).scheme in {'http','https'} else ''})
            if len(results) == limit:
                break
    except Exception as exc:
        _note_ddg_failure(exc)
        return json.dumps({'status':'FAILED','reason':'image_search_transport_failed',
                           'error_type':type(exc).__name__,'results':[]})
    if delivery == 'links':
        return json.dumps({'status':'SUCCESS' if results else 'UNVERIFIED','results':results,
            'downloaded':False,'content_verified':False,
            'instruction':'Unreviewed search links only. Do not claim image contents, official status or usage rights were verified.'})
    from core.image_download import save_verified_image
    artifacts, failures, rejected, seen_images = [], [], [], set()
    stop_reason = 'candidates_exhausted'
    for offset in range(0,len(results),6):
        batch = []
        for result in results[offset:offset+6]:
            if time.monotonic() >= deadline - 10:
                stop_reason = 'review_budget_exhausted'
                break
            try:
                artifact = save_verified_image(result['image_url'],BASE_DIR)
                fingerprint = hashlib.sha256(preview(artifact).encode()).hexdigest()
                if fingerprint in seen_images:
                    rejected.append({'reason':'duplicate_image'})
                    continue
                seen_images.add(fingerprint)
                batch.append({**artifact,'source_url':result['source_url']})
            except Exception as exc:
                failures.append({'error_type':type(exc).__name__})
        if batch:
            remaining = deadline - time.monotonic()
            if remaining < 10:
                stop_reason = 'review_budget_exhausted'
                break
            try:
                verdicts = review_images(query,batch,timeout=min(30,remaining))
            except Exception as exc:
                stop_reason = 'visual_review_failed'
                failures.append({'stage':'visual_review','error_type':type(exc).__name__})
                break
            for artifact, verdict in zip(batch,verdicts):
                if verdict['matches']:
                    if len(artifacts) < count:
                        artifacts.append({**artifact,'content_verified':True,'review':verdict})
                else:
                    rejected.append({'reason':verdict['reason']})
        if len(artifacts) == count:
            stop_reason = 'requested_count_met'
            break
        if stop_reason == 'review_budget_exhausted':
            break
    log_review(BASE_DIR, requested_count=count, accepted_count=len(artifacts),
               rejected_count=len(rejected), failure_count=len(failures), stop_reason=stop_reason)
    return json.dumps({'status':'UNVERIFIED' if artifacts else 'FAILED','verified':False,
        'image_artifacts':artifacts,'download_failures':failures,'rejected_candidates':rejected,
        'requested_count':count,'candidate_count':len(results),'matched_count':len(artifacts),
        'partial':len(artifacts)<count,'downloaded':bool(artifacts),'content_review':'configured_text_model',
        'stop_reason':stop_reason,
        'instruction':'Only visually matched images are eligible for Inbox delivery. Report matched/delivered counts against the requested count, including shortages. Never replace rejected candidates with unreviewed files. Visual assessment can err and does not certify official status, source facts, exact original text or copyright.'},ensure_ascii=False)


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    try:
        if mode == "images":
            return _images(query, str(params.get("delivery") or "attachments"), params.get("count", 6))
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "web_search",
    "description": "Searches the web. Use for ANY question about current facts, events, prices, or topics — always prefer this over guessing. For pictures, posters or image requests use mode='images' to visually review actual candidates against the complete query and deliver matching images to companion Inbox. Preserve requested image type, subject, text/year and completeness in query; report shortages. Unsupported visual input returns BLOCKED without fallback. Use delivery=links only when links were requested. Do not substitute a TXT list of links for images. Modes: 'search' (default), 'news' (latest headlines on a topic), 'research' (deep comprehensive answer), 'price' (product cost lookup), 'compare' (side-by-side comparison of items).",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Search query or topic"
            },
            "mode": {
                "type": "STRING",
                "description": "search | images | news | research | price | compare"
            },
            "count": {"type":"INTEGER", "description":"Image count requested by user, default 6; 1-20 per request. Split larger requests explicitly, never silently truncate."},
            "delivery": {"type":"STRING", "enum":["attachments","links"], "description":"Image mode defaults to attachments; links only on explicit request."},
            "items": {
                "type": "ARRAY",
                "items": {
                    "type": "STRING"
                },
                "description": "Items to compare (compare mode)"
            },
            "aspect": {
                "type": "STRING",
                "description": "Comparison aspect: price | specs | reviews | features"
            }
        },
        "required": [
            "query"
        ]
    },
    "handler": web_search,
}
