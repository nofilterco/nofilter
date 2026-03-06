import random
import time

# ---- Fallback list (your original) ----
TREND_BUCKETS = [
    "minimalist streetwear",
    "gym motivation",
    "funny dad humor",
    "retro 90s aesthetic",
    "AI tech culture",
    "coffee lovers",
    "entrepreneur mindset",
    "dark humor quotes",
]

# Simple in-memory cache to avoid hammering Trends every run
_CACHE = {"ts": 0, "items": []}
CACHE_TTL_SECONDS = 60 * 30  # 30 minutes


def _fallback():
    return random.choice(TREND_BUCKETS)


def _safe_pick(items):
    items = [x for x in items if isinstance(x, str) and x.strip()]
    if not items:
        return None
    return random.choice(items)


def _fetch_from_pytrends():
    """
    Uses pytrends to grab "related queries" from a random seed keyword.
    This gives you *real* currently-related searches (often trend-adjacent).
    """
    try:
        from pytrends.request import TrendReq
    except Exception:
        return None

    try:
        pytrends = TrendReq(hl="en-US", tz=360)

        seeds = [
            "streetwear",
            "gym motivation",
            "retro aesthetic",
            "coffee lovers",
            "dad jokes",
            "entrepreneur",
            "dark humor",
            "minimalist",
            "y2k fashion",
            "90s vintage",
        ]
        seed = random.choice(seeds)

        pytrends.build_payload([seed], timeframe="now 7-d")
        rq = pytrends.related_queries()

        if seed not in rq:
            return None

        top_df = rq[seed].get("top")
        rising_df = rq[seed].get("rising")

        candidates = []
        if top_df is not None and not top_df.empty and "query" in top_df.columns:
            candidates.extend(top_df["query"].astype(str).tolist())

        if rising_df is not None and not rising_df.empty and "query" in rising_df.columns:
            candidates.extend(rising_df["query"].astype(str).tolist())

        return _safe_pick(candidates)

    except Exception:
        # Any error (rate limit, network, etc.) -> let caller fallback
        return None


def get_trending_niche():
    """
    Returns a niche phrase. Uses live pytrends when available, otherwise fallback buckets.
    """
    now = time.time()

    # Use cached trends if fresh
    if _CACHE["items"] and (now - _CACHE["ts"]) < CACHE_TTL_SECONDS:
        pick = _safe_pick(_CACHE["items"])
        return pick or _fallback()

    # Try live source
    pick = _fetch_from_pytrends()
    if pick:
        _CACHE["items"] = [pick]  # keep simple; you can store more later
        _CACHE["ts"] = now
        return pick

    # Fallback
    return _fallback()