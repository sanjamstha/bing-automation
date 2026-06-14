"""
tasks/queries.py — Search Query Generator

Provides get_queries(count) — the single public function used by search.py.

Strategy:
  Primary   — Fetch `count` random Wikipedia article titles in one HTTP call.
               Real, varied, human-looking titles with zero hardcoded content.
  Fallback  — If the Wikipedia fetch fails for any reason, generate queries
               locally via a topic + modifier + prefix combinator.
               Visible warning is logged so the operator knows which path ran.

This module is intentionally decoupled from device/UI logic — it has no
dependency on uiautomator2, ADB, or any Bing-specific code.
"""

import random
import requests
from core.device import log

# ── Combinator constants (fallback only) ───────────────────────────

_TOPICS = [
    "hiking", "coffee", "sushi", "yoga", "chess",
    "cycling", "gardening", "photography",  "cooking", "skiing",
    "pottery", "origami", "surfing", "painting", "camping",
    "knitting", "bouldering", "archery", "foraging", "beekeeping",
    "calligraphy", "astronomy", "birdwatching", "fermentation", "woodworking",
]  # 25 topics

_MODIFIERS = [
    "near me", "tips", "best", "how to", "for beginners",
    "guide",   "cheap", "review", "ideas", "techniques",
]  # 10 modifiers

_PREFIXES = list("abcdefghijklmnopqrstuvwxyz0123456789")  # 36 chars

# Total unique combinations: 25 × 10 × 36 = 9,000


# ── Wikipedia fetch ────────────────────────────────────────────────

def _fetch_wikipedia_titles(count):
    """
    Fetches `count` random Wikipedia article titles in a single HTTP call.
    Uses the MediaWiki Action API with generator=random.

    Raises RuntimeError (or any requests exception) on any failure so that
    get_queries() can catch it and fall through to the combinator.
    """
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action":       "query",
        "generator":    "random",
        "grnnamespace": "0",          # real articles only — no Talk/Category pages
        "grnlimit":     count + 5,    # fetch a few extra as buffer for empty/bad titles
        "prop":         "info",
        "format":       "json",
    }
    headers = {
        "User-Agent": "ContentReader",
    }

    response = requests.get(url, params=params, headers=headers, timeout=8)

    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")

    pages = response.json()["query"]["pages"]

    titles = [
        page["title"].strip()
        for page in pages.values()
        if page.get("title", "").strip()
    ]

    if len(titles) < count:
        raise RuntimeError(
            f"Wikipedia returned only {len(titles)} titles, needed {count}"
        )

    return titles[:count]


# ── Combinator fallback ────────────────────────────────────────────

def _generate_queries(count):
    """
    Generates `count` unique queries by combining a random prefix, topic,
    and modifier. Uses a set for deduplication.

    Safety guard: max count * 10 iterations to prevent an infinite loop
    if count approaches the total combination space. Any remaining slots
    after the guard are filled with plain topic strings.

    Returns a shuffled list of exactly `count` query strings.
    """
    if count == 0:
        return []

    queries  = set()
    max_iter = count * 10
    iters    = 0

    while len(queries) < count and iters < max_iter:
        q = (
            random.choice(_PREFIXES)
            + random.choice(_TOPICS)
            + " "
            + random.choice(_MODIFIERS)
        )
        queries.add(q)
        iters += 1

    # Safety fill — should never trigger in practice (count << 9,000)
    while len(queries) < count:
        queries.add(random.choice(_TOPICS))

    result = list(queries)
    random.shuffle(result)
    return result


# ── Public interface ───────────────────────────────────────────────

def get_queries(count):
    """
    Returns a list of `count` unique search query strings.

    Tries Wikipedia first. Falls back to the combinator on any failure.
    Always logs which path ran and why, so the operator can see it in console.
    """
    if count == 0:
        return []

    try:
        titles = _fetch_wikipedia_titles(count)
        log(f"  [QUERIES] Fetched {count} titles from Wikipedia ✓")
        return titles
    except Exception as e:
        log(f"  [WARN] Wikipedia fetch failed ({e.__class__.__name__}: {e})"
            f" — falling back to combinator.")
        queries = _generate_queries(count)
        log(f"  [QUERIES] Generated {count} queries via combinator fallback ✓")
        return queries