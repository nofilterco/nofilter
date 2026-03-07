import os
import random
from typing import Dict, List
from dotenv import load_dotenv

from nostalgia_blueprint import get_phrases, detect_risk, choose_slogan

load_dotenv()


PHRASE_LIBRARY: Dict[str, List[str]] = {
    "nostalgia_status": [
        "PROBABLY BUFFERING",
        "USER BUSY",
        "LOW BATTERY",
        "CACHE MISS",
        "OFFLINE TODAY",
    ],
    "fake_departments": [
        "LATE FEES DEPT",
        "REWIND SERVICE",
        "AFTER SCHOOL CLUB",
        "VIDEO STORE STAFF",
    ],
    "dry_humor": [
        "TOUCH GRASS LATER",
        "SEEN ONLINE",
        "NOT NOW",
        "TRY AGAIN TOMORROW",
    ],
    "nostalgia_tech": [
        "DIAL TONE",
        "ANALOG HEART",
        "VHS ENERGY",
        "BUFFERING AGAIN",
    ],
}

PHRASE_CATEGORY_WEIGHTS = {
    "nostalgia_status": 30,
    "fake_departments": 20,
    "dry_humor": 30,
    "nostalgia_tech": 20,
}


def _library_phrases(max_words: int = 4, max_chars: int = 24) -> List[str]:
    phrases: List[str] = []
    for items in PHRASE_LIBRARY.values():
        for phrase in items:
            clean = (phrase or "").strip().upper()
            if clean and len(clean.split()) <= max_words and len(clean) <= max_chars:
                phrases.append(clean)
    return phrases


def pick_phrase_category() -> str:
    categories = list(PHRASE_CATEGORY_WEIGHTS.keys())
    return random.choices(categories, weights=[PHRASE_CATEGORY_WEIGHTS[c] for c in categories], k=1)[0]

def pick_phrase(niche: str = "") -> str:
    """Return a short, embroidery-friendly phrase.

    Controlled by env:
      - CUSTOM_PHRASE (optional override)
      - PHRASE_TIER = safe|edgy
    """
    custom = (os.getenv("CUSTOM_PHRASE") or "").strip()
    if custom:
        risk = detect_risk(custom)
        if risk:
            raise ValueError(f"Custom phrase blocked by safety gate: {risk}")
        return custom

    tier = (os.getenv("PHRASE_TIER") or "safe").strip().lower()
    strategy = os.getenv("PHRASE_STRATEGY", "typography_first").strip().lower()
    library = _library_phrases(max_words=4, max_chars=24)
    phrases = get_phrases(tier)
    short_phrases = [p for p in phrases if len((p or "").strip()) <= 24 and len((p or "").split()) <= 4]
    phrase = random.choice(short_phrases or phrases) if (short_phrases or phrases) else "NO FILTER"

    if strategy in ("typography_first", "nostalgia", "strong", "v2"):
        category = pick_phrase_category()
        pool = [p for p in PHRASE_LIBRARY.get(category, []) if len(p.split()) <= 4]
        phrase = random.choice(pool or library or [phrase])
    elif strategy == "hybrid":
        phrase = random.choice(library or short_phrases or [phrase])
    elif strategy == "legacy_slogan":
        phrase = choose_slogan(
            humor_mode=random.choice(["deadpan", "understated", "club_irony", "low_energy"]),
            slogan_type=random.choice([
                "dry_humor",
                "faux_corporate",
                "fake_club",
                "fake_department",
                "status_phrases",
                "nostalgic_emotional",
                "old_tech",
                "low_energy_meme",
            ]),
            max_chars=24,
        )
    # final safety gate
    risk = detect_risk(phrase)
    if risk:
        # fallback to safe tier
        phrases2 = get_phrases("safe")
        phrase2 = random.choice(phrases2) if phrases2 else "NO FILTER"
        return phrase2
    return phrase
