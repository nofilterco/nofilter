import os
import random
from dotenv import load_dotenv

from nostalgia_blueprint import get_phrases, detect_risk

load_dotenv()

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
    phrases = get_phrases(tier)
    phrase = random.choice(phrases) if phrases else "NO FILTER"
    # final safety gate
    risk = detect_risk(phrase)
    if risk:
        # fallback to safe tier
        phrases2 = get_phrases("safe")
        phrase2 = random.choice(phrases2) if phrases2 else "NO FILTER"
        return phrase2
    return phrase
