import os
import random
from dotenv import load_dotenv

from nostalgia_blueprint import get_phrases, detect_risk, choose_slogan

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
    # Keep phrases embroidery-safe and short by default
    short_phrases = [p for p in phrases if len((p or "").strip()) <= 20 and len((p or "").split()) <= 3]
    phrase = random.choice(short_phrases or phrases) if (short_phrases or phrases) else "NO FILTER"
    # strengthen text output for hats with categorized short sayings
    if os.getenv("PHRASE_STRATEGY", "nostalgia").strip().lower() in ("nostalgia", "strong", "v2"):
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
            max_chars=20,
        )
    # final safety gate
    risk = detect_risk(phrase)
    if risk:
        # fallback to safe tier
        phrases2 = get_phrases("safe")
        phrase2 = random.choice(phrases2) if phrases2 else "NO FILTER"
        return phrase2
    return phrase
