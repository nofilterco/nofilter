import os
import random
import re
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from nostalgia_blueprint import detect_risk

load_dotenv()


CURATED_PHRASE_BUCKETS: Dict[str, List[str]] = {
    "nostalgia_status": [
        "PROBABLY BUFFERING", "OFFLINE TODAY", "REWIND LATER", "USER BUSY", "CACHE MISS",
        "SOFT REBOOT", "SIGNAL WEAK", "AFK BRIEFLY", "SAVED LOCALLY", "STILL LOADING",
        "DIAL TONE", "PLAYBACK ERROR", "MEMORY FULL", "LOW BATTERY", "PAUSED AGAIN",
    ],
    "old_tech_status": [
        "ANALOG HEART", "CRT FRIENDLY", "FLOPPY READY", "MODEM MIND", "PAGER MODE",
        "RENTAL COPY", "VHS ENERGY", "MANUAL SYNC", "SYNC PENDING", "INSERT TAPE",
        "NO AUTOSAVE", "LOCAL ONLY", "DISK TWO", "BOOT MENU", "PRESSED PLAY",
    ],
    "faux_departments": [
        "LATE FEES DEPT", "QUIET HOURS DEPT", "SLOW REPLY DESK", "REWIND DEPT", "COOL DOWN DEPT",
        "SNACK BREAK DEPT", "LOGOUT DEPT", "TAPE REPAIR UNIT", "LOW POWER OFFICE", "SOFT RESET DESK",
        "PARKING LOT DEPT", "SCREEN BREAK UNIT", "DAYDREAM DESK", "BUFFER TEAM", "TRAVEL MODE DESK",
    ],
    "faux_clubs": [
        "AFTER SCHOOL CLUB", "LOW BATTERY CLUB", "OFFLINE CLUB", "NIGHT MODE CLUB", "NO RUSH CLUB",
        "LATE CHECKOUT CLUB", "MALL WALK CLUB", "REWIND CLUB", "SIDE QUEST CLUB", "SILENT MODE CLUB",
        "SLOW INTERNET CLUB", "COUCH CREW CLUB", "ANALOG CLUB", "PARKING LOT CLUB", "SNACK RUN CLUB",
    ],
    "faux_services": [
        "REWIND SERVICE", "SOFT REBOOT SERVICE", "CALM MODE SERVICE", "AFTER HOURS SERVICE", "BUFFERING SERVICE",
        "QUIET DESK SERVICE", "SLOW LANE SERVICE", "OFFLINE SUPPORT", "LOCAL CACHE SERVICE", "SCREEN BREAK SERVICE",
        "MANUAL UPDATE", "RECOVERY SERVICE", "RESET SERVICE", "RETRY SERVICE", "NO RUSH SUPPORT",
    ],
    "dry_humor": [
        "DO NOT DISTURB", "NOT TODAY", "TRY AGAIN LATER", "MAYBE TOMORROW", "PENDING FOREVER",
        "TOUCH GRASS LATER", "SEEN ONLINE", "UNAVAILABLE", "STILL THINKING", "NOT URGENT",
        "CURRENTLY BUFFERING", "BUSY RELAXING", "DEFERRED RESPONSE", "ON A BREAK", "QUIETLY OFFLINE",
    ],
    "low_energy_meme": [
        "LOW SOCIAL BATTERY", "MINIMAL EFFORT", "USER TIRED", "SLOW MODE", "LAGGING TODAY",
        "NOT FULLY LOADED", "BUFFERING HUMAN", "NOPE MODE", "IDLE STATUS", "SLEEP MODE",
        "SHORT CIRCUIT", "STARTUP DELAY", "MUTED ENERGY", "BATTERY SAVER", "RESPONSE LAG",
    ],
    "after_school_life": [
        "AFTER SCHOOL", "BUS STOP HOURS", "SNACK BREAK", "LOCKER ENERGY", "HOMEWORK LATER",
        "RECESS MINDSET", "MALL FOOD COURT", "PARKING LOT TALKS", "TV GUIDE NIGHT", "WEEKEND RENTAL",
        "COUCH CHECK IN", "FRIDAY CLUB", "BACKPACK MODE", "AIM AWAY", "SCHOOL NIGHT",
    ],
    "mall_culture": [
        "MALL CERTIFIED", "FOOD COURT VIP", "ARCADE TOKEN", "WINDOW SHOPPING", "OPEN LATE",
        "PARKING LOT MEETUP", "MALL WALK", "RECEIPT KEEPER", "SATURDAY MALL", "RINK NIGHT",
        "NEON COURT", "TOKEN ONLY", "FITTING ROOM BREAK", "STICKER KIOSK", "COURT SIDE",
    ],
    "offline_lifestyle": [
        "OFFLINE LIFESTYLE", "LOCAL HOURS", "AIRPLANE MODE", "QUIET MODE", "NO WIFI MOOD",
        "OUTSIDE BRIEFLY", "DND ACTIVE", "UNPLUGGED", "ANALOG WEEKEND", "NO PUSH ALERTS",
        "SCREEN BREAK", "MUTE NOTIFS", "LOW STIM MODE", "SLOW SUNDAY", "MANUAL DAY",
    ],
    "internet_lag": [
        "INTERNET LAG", "CONNECTION LOST", "RECONNECTING", "LOADING LOOP", "BUFFER EVENT",
        "PACKET LOSS", "LATENCY CLUB", "SPINNING ICON", "WEAK SIGNAL", "RETRYING",
        "CACHE STALL", "CONNECTION PENDING", "PING TOO HIGH", "NETWORK BUSY", "UPLOAD LATER",
    ],
    "analog_emotional": [
        "ANALOG FEELINGS", "SOFT STATIC", "WARM NOISE", "CLOUDY SIGNAL", "HEART IN DRAFTS",
        "SENT UNSENT", "QUIET FREQUENCY", "SLOW MOTION", "MOONLIT BUFFER", "NIGHT SHIFT HEART",
        "CALM CHAOS", "FUZZY MEMORY", "UNSCHEDULED JOY", "TENDER ERROR", "SINCERE LAG",
    ],
}

CATEGORY_WEIGHTS: Dict[str, int] = {
    "nostalgia_status": 12,
    "old_tech_status": 12,
    "faux_departments": 10,
    "faux_clubs": 10,
    "faux_services": 8,
    "dry_humor": 12,
    "low_energy_meme": 10,
    "after_school_life": 8,
    "mall_culture": 6,
    "offline_lifestyle": 6,
    "internet_lag": 4,
    "analog_emotional": 2,
}


def _normalize_phrase(phrase: str) -> str:
    return re.sub(r"\s+", " ", (phrase or "").strip().upper())


def _word_count(phrase: str) -> int:
    return len([w for w in phrase.split(" ") if w])


def phrase_scores(phrase: str, category: str = "") -> Dict[str, int]:
    p = _normalize_phrase(phrase)
    words = _word_count(p)
    chars = len(p)
    tokens = p.split()

    wearable = 10
    if words > 4 or chars > 22:
        wearable -= 4
    if words == 1 and chars <= 12:
        wearable += 1

    readability = 10
    if chars > 20:
        readability -= 2
    if any(len(t) > 11 for t in tokens):
        readability -= 2

    humor = 5
    humor_markers = {"BUFFER", "LAG", "BUSY", "LATER", "CLUB", "DEPT", "SERVICE", "MISS", "OFFLINE"}
    if any(marker in p for marker in humor_markers):
        humor += 3

    nostalgia = 5
    nostalgia_markers = {"ANALOG", "VHS", "CRT", "REWIND", "FLOPPY", "MODEM", "MALL", "ARCADE", "TAPE"}
    if any(marker in p for marker in nostalgia_markers):
        nostalgia += 3
    if category in {"nostalgia_status", "old_tech_status", "after_school_life", "mall_culture", "analog_emotional"}:
        nostalgia += 1

    novelty = 6
    if len(set(tokens)) == len(tokens):
        novelty += 1
    if p.endswith(("CLUB", "DEPT", "SERVICE")):
        novelty += 1

    return {
        "wearable_score": max(1, min(10, wearable)),
        "humor_score": max(1, min(10, humor)),
        "nostalgia_score": max(1, min(10, nostalgia)),
        "readability_score": max(1, min(10, readability)),
        "novelty_score": max(1, min(10, novelty)),
    }


def _is_valid_phrase(phrase: str) -> bool:
    p = _normalize_phrase(phrase)
    return bool(p and _word_count(p) <= 4 and len(p) <= 20 and not detect_risk(p))


def _pick_phrase_from_category(category: str) -> Tuple[str, Dict[str, int]]:
    pool = [_normalize_phrase(p) for p in CURATED_PHRASE_BUCKETS.get(category, []) if _is_valid_phrase(p)]
    random.shuffle(pool)
    best_phrase = "NO FILTER"
    best_score = -1
    best_scores = phrase_scores(best_phrase, category)
    for candidate in pool:
        scores = phrase_scores(candidate, category)
        total = scores["wearable_score"] + scores["readability_score"] + scores["novelty_score"] + scores["humor_score"]
        if total > best_score:
            best_phrase, best_score, best_scores = candidate, total, scores
    return best_phrase, best_scores


def pick_phrase_category() -> str:
    cats = list(CATEGORY_WEIGHTS.keys())
    return random.choices(cats, weights=[CATEGORY_WEIGHTS[c] for c in cats], k=1)[0]


def pick_phrase(niche: str = "", *, category_override: Optional[str] = None) -> str:
    custom = _normalize_phrase((os.getenv("CUSTOM_PHRASE") or "").strip())
    if custom:
        if not _is_valid_phrase(custom):
            raise ValueError("Custom phrase blocked by safety/format gate")
        return custom

    strategy = (os.getenv("PHRASE_STRATEGY", "curated_merch").strip().lower())
    category = (category_override or os.getenv("PHRASE_CATEGORY") or "").strip().lower()
    if category not in CURATED_PHRASE_BUCKETS:
        category = pick_phrase_category()

    # reroll weak outcomes
    for _ in range(8):
        phrase, scores = _pick_phrase_from_category(category)
        avg = sum(scores.values()) / 5.0
        if strategy in ("curated_merch", "typography_first", "v2", "strong"):
            if scores["wearable_score"] >= 7 and scores["readability_score"] >= 7 and avg >= 7:
                return phrase
        else:
            return phrase

    return "OFFLINE TODAY"
