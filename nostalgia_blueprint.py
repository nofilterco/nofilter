"""
NoFilterCo — 80s/90s/2000s Nostalgia Blueprint (V4)

Goal:
Generate copyright-safe, embroidery-friendly, subtle nostalgia designs inspired by
late 80s, 90s, and early 2000s culture — mall era, analog tech, early internet weirdness,
playground energy, and adult millennial humor (“No Filter” energy).

V4 Highlights:
- Anti-repetition expansion (micro-niches, object states, contexts, situations, texture cues)
- Expanded motif pools (supports 500+ unique designs without repeating “the same icon”)
- Drop personality profiles (weighted styles + tones per drop)
- Controlled “EDGY_MODE” (still Shopify/Printify safe)
- Option B support: seed-time fields are stable and can be stored in queue.csv

Safety:
- Avoid copyrighted characters, TV shows, brand names, distinctive console shapes, lyrics, or trademark phrases.
- Favor generic, original iconography and short, generic text.
- No direct references to specific media properties.
- No hate speech, slurs, explicit sexual content, drug references, or violence threats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import os
import random
import re

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


# =========================
# Utilities
# =========================
def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    out: List[str] = []
    last_dash = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        else:
            if not last_dash:
                out.append("-")
                last_dash = True
    return "".join(out).strip("-")[:80]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-")


def _pick_weighted(options: List[Tuple[str, int]]) -> str:
    # options: [(value, weight), ...]
    total = sum(max(0, w) for _, w in options) or 1
    r = random.randint(1, total)
    acc = 0
    for val, w in options:
        w = max(0, w)
        acc += w
        if r <= acc:
            return val
    return options[0][0]


def _env_true(name: str, default: str = "0") -> bool:
    v = (os.getenv(name, default) or "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


# =========================
# Embroidery constraints
# =========================
@dataclass
class EmbroideryConfig:
    canvas_width_px: int = 1200
    canvas_height_px: int = 675
    canvas_dpi: int = 300
    embroidery_width_in: float = 4.0
    embroidery_height_in: float = 2.25
    safe_width_in: float = 3.5
    safe_height_in: float = 2.0
    max_colors: int = 6
    min_detail_in: float = 0.06
    min_text_in: float = 0.2
    allowed_thread_palette: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.allowed_thread_palette is None:
            self.allowed_thread_palette = [
                "#000000", "#96a1a8", "#ffffff", "#660000", "#cc3333",
                "#cc3366", "#a67843", "#e25c27", "#ffcc00", "#01784e",
                "#7ba35a", "#333366", "#005397", "#3399ff", "#6b5294",
            ]


def load_embroidery_config(path: str = "nofilter.yaml") -> EmbroideryConfig:
    default = EmbroideryConfig()
    if not yaml or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return default

    emb = data.get("embroidery") or {}
    if not isinstance(emb, dict):
        return default

    return EmbroideryConfig(
        canvas_width_px=int(emb.get("canvas_width_px", default.canvas_width_px)),
        canvas_height_px=int(emb.get("canvas_height_px", default.canvas_height_px)),
        canvas_dpi=int(emb.get("canvas_dpi", default.canvas_dpi)),
        embroidery_width_in=float(emb.get("embroidery_width_in", default.embroidery_width_in)),
        embroidery_height_in=float(emb.get("embroidery_height_in", default.embroidery_height_in)),
        safe_width_in=float(emb.get("safe_width_in", default.safe_width_in)),
        safe_height_in=float(emb.get("safe_height_in", default.safe_height_in)),
        max_colors=int(emb.get("max_colors", default.max_colors)),
        min_detail_in=float(emb.get("min_detail_in", default.min_detail_in)),
        min_text_in=float(emb.get("min_text_in", default.min_text_in)),
        allowed_thread_palette=[str(x) for x in (emb.get("allowed_thread_palette") or default.allowed_thread_palette)],
    )


EMBROIDERY_CONFIG = load_embroidery_config()
MAX_THREAD_COLORS = EMBROIDERY_CONFIG.max_colors
HAT_TEMPLATE = {
    "width_px": EMBROIDERY_CONFIG.canvas_width_px,
    "height_px": EMBROIDERY_CONFIG.canvas_height_px,
    "dpi": EMBROIDERY_CONFIG.canvas_dpi,
    "width_in": EMBROIDERY_CONFIG.embroidery_width_in,
    "height_in": EMBROIDERY_CONFIG.embroidery_height_in,
    "safe_width_in": EMBROIDERY_CONFIG.safe_width_in,
    "safe_height_in": EMBROIDERY_CONFIG.safe_height_in,
}


# =========================
# Visual archetypes / styles (expanded)
# =========================
STYLE_DIRECTIVES: Dict[str, str] = {
    "centered-emblem": "Single centered emblem with strong silhouette and flat fills for direct hat-front embroidery.",
    "monoline-symbol": "Single symbol using thick monoline geometry and minimal interior detail.",
    "bold-icon-block": "Chunky icon block with clear negative space and stitch-safe outlines.",
    "geometric-monogram": "Simple geometric monogram with thick strokes and no tiny counters.",
    "simplified-mascot-icon": "Minimal mascot-like icon built from basic shapes, no texture, no scene.",
    "direct-front-graphic": "Single compact front graphic with centered weight and transparent background.",
    "wordmark-icon": "Short bold wordmark paired with one simple icon, embroidery-safe spacing.",
    "framed-motif": "Optional motif-specific frame only when intrinsic to the motif concept.",
}

STYLE_CHOICES = list(STYLE_DIRECTIVES.keys())


# =========================
# Tones (safe) + Edgy (still safe)
# =========================
TONE_LAYERS = [
    "premium understated nostalgia",
    "deadpan adult nostalgia",
    "subtle millennial humor",
    "raised offline pride",
    "sleepover survivor energy",
    "mall kid nostalgia",
    "analog childhood pride",
    "light existential humor",
    "calm retro tech minimalism",
]

# “Edgy” but still within typical Shopify/Printify bounds:
# (No slurs, no explicit sexual content, no explicit drug refs, no threats)
EDGY_TONES = [
    "emotionally buffering energy",
    "low battery adult humor",
    "mentally offline tone",
    "mild sarcastic apathy",
    "existential lag energy",
    "former gifted kid burnout humor",
]


# =========================
# Anti-repetition components
# =========================
MICRO_NICHES = [
    # Analog life moments
    "desk clutter",
    "backpack interior",
    "bedroom floor pile",
    "garage sale box",
    "junk drawer",
    "computer lab desk",
    "after school snack table",
    "sleepover floor",
    "car backseat",
    "mall food court tray",
    "TV stand shelf",
    "media cabinet",
    "under the TV",
    "school desk",
    "locker interior",
    "recess ground",
    "sidewalk chalk area",
]

OBJECT_STATES = [
    "brand new",
    "slightly worn",
    "scuffed",
    "taped",
    "labeled",
    "cracked",
    "partially open",
    "half inserted",
    "stacked unevenly",
    "spilled out",
    "tangled",
    "rewound halfway",
    "paused mid-use",
]

ERA_SITUATIONS = [
    "after school",
    "sleepover",
    "computer lab",
    "mall food court",
    "Saturday morning",
    "family living room",
    "late-night homework session",
    "weekend cleanup / closet purge",
]

TEXTURE_CUES = [
    "light scuff marks (stitch-safe)",
    "tape residue (stitch-safe)",
    "handwritten label (generic, stitch-safe)",
    "creased corner (stitch-safe)",
    "slight crack line (stitch-safe)",
    "worn edges (stitch-safe)",
    "adhesive residue (no brands, stitch-safe)",
]

VARIATION_MODIFIERS = [
    "centered object",
    "top view",
    "side view",
    "single compact mark",
    "simplified geometric build",
    "thick-outline variant",
]

TEXT_PAIRING_CONTEXTS = [
    "front embroidery lockup",
    "clean vector lockup",
    "compact emblem lockup",
]

MOTIF_FAMILIES = [
    "single-emblem",
    "symbol",
    "simplified-mascot",
    "monogram",
    "direct-front-graphic",
]

MOTIF_FRAMES = [
    "none",
    "circle",
    "shield",
    "hex",
]

PRODUCT_RULES = {
    "hat": {
        "canvas_px": (HAT_TEMPLATE["width_px"], HAT_TEMPLATE["height_px"]),
        "dpi": HAT_TEMPLATE["dpi"],
        "size_in": (HAT_TEMPLATE["width_in"], HAT_TEMPLATE["height_in"]),
        "safe_in": (HAT_TEMPLATE["safe_width_in"], HAT_TEMPLATE["safe_height_in"]),
        "focus": "centered front panel",
    }
}


# =========================
# Phrase pools (safe)
# =========================
SOFT_PHRASES = [
    "NO FILTER",
    "OFFLINE MODE",
    "NO WIFI ZONE",
    "LOADING...",
    "BUFFERING...",
    "ANALOG ERA",
    "RECESS FOREVER",
    "STAY ANALOG",
    "SIGNAL LOST",
    "SAVED LOCALLY",
    "RETRO MODE",
    "CONNECTING...",
    "PLEASE WAIT",
    "TRY AGAIN",
    "OUT OF ORDER",
    "INSERT COIN",
    "DO NOT DISTURB",
    "SYSTEM BUSY",
]

ADULT_MILLENNIAL_PHRASES = [
    "FORMER GIFTED KID",
    "LOW BATTERY ADULT",
    "LOADING SINCE 1994",
    "FUNCTIONING SINCE 1997",
    "PEAKED IN 2003",
    "SURVIVED DIAL-UP",
    "RAISED OFFLINE",
    "CERTIFIED MALL KID",
    "RECESS VETERAN",
    "STILL BUFFERING",
    "MEMORY FULL",
    "CACHE CLEARED",
    "SYSTEM OVERWHELMED",
    "SOFT RESET",
    "PLEASE STAND BY",
    "RUNNING ON TWO BARS",
    "MENTALLY IN 2002",
    "EXISTENTIAL LAG",
    "PROCESSING...",
]

# “Edgy” set stays platform-safe (no profanity required to be funny)
EDGY_PHRASES = [
    "EMOTIONALLY BUFFERING",
    "MENTALLY OFFLINE",
    "LOW SIGNAL HUMAN",
    "NOT NOW",
    "ARE YOU SURE?",
    "DO NOT PERCEIVE ME",
    "CURRENTLY UNAVAILABLE",
    "OUT OF OFFICE (EMOTIONALLY)",
    "SYSTEM ERROR",
    "PLEASE TRY LATER",
    "MINIMAL ENERGY MODE",
]


# Backward-compatible constant expected by older phrase_engine versions:
# (We keep this, but also provide get_safe_phrases().)
SAFE_PHRASES = list(dict.fromkeys(SOFT_PHRASES + ADULT_MILLENNIAL_PHRASES + EDGY_PHRASES))


# =========================
# Expanded motifs (generic, original, safe)
# =========================
# Keep motifs generic and avoid brand names / specific media properties.

ANALOG_SUPER_MOTIFS = [
    # Media
    "VHS tape with handwritten label (generic)",
    "blank VHS tape with tape window",
    "VHS tape stack tied with rubber band",
    "cassette tape with tangled tape",
    "cassette tape with tape spilling out",
    "cassette tape labeled MIX (generic)",
    "cassette tape inside clear case",
    "open cassette case on surface",
    "stack of mixed tapes in a cardboard box",
    "portable CD player with headphones (generic)",
    "wired headphones tangled",
    "boombox with cassette inside (generic)",
    "media shelf stack (VHS + tapes) simplified",

    # Floppy / storage
    "stack of floppy disks with labels (generic)",
    "floppy disk half inserted into a computer slot (generic)",
    "pile of mismatched floppy disks",
    "diskette case partially open (generic)",
    "stack of labeled disks beside keyboard (generic)",

    # Living room tech
    "CRT TV with static screen (generic)",
    "CRT TV with VCR below (generic)",
    "VCR with blinking clock (generic)",
    "VCR ejecting tape (generic)",
    "remote control outline (generic buttons)",
    "TV stand shelf with tapes (generic)",

    # Symbols
    "rewind arrows symbol (double triangle icon)",
    "fast-forward arrows symbol (double triangle icon)",
    "pause icon (generic)",
    "record dot icon (generic)",
    "battery indicator icon (low battery state, generic)",
    "dial knob and slider cluster (generic)",
]

PLAYGROUND_SUPER_MOTIFS = [
    "backpack spilling school supplies",
    "zipper pouch with pens",
    "stack of spiral notebooks (generic)",
    "pile of crumpled homework papers",
    "lunchbox with thermos (generic)",
    "half-eaten snack on tray (generic)",
    "yo-yo tangled with jump rope (generic)",
    "jump rope loop icon (minimal curve graphic)",
    "chalk bucket tipped over",
    "chalk drawings partially erased",
    "locker shelf with books (generic)",
    "school desk top view",
    "recess whistle icon (simple silhouette)",
    "hopscotch grid icon (generic)",
    "playground slide outline icon",
    "smiley doodle (original, minimal)",
    "clean lightning bolt icon (original shape)",
]

INTERNET_SUPER_MOTIFS = [
    "computer lab row of monitors (generic)",
    "CRT monitor with error box (generic)",
    "desktop computer with sticky notes (generic)",
    "tower with floppy inserted (generic)",
    "keyboard with worn keys",
    "mouse with tangled cord",
    "loading bar icon (generic segmented bar)",
    "buffering dots icon (three dots)",
    "cursor arrow icon (original vector style)",
    "signal strength bars icon (generic ascending bars)",
    "dialog window outline (generic UI box)",
    "hourglass icon (generic)",
    "globe wireframe icon (generic lines)",
    "email envelope icon (generic)",
    "CD spindle case with discs (generic)",
    "stack of generic promo discs (unlabeled)",
]

MALL_SUPER_MOTIFS = [
    "food court tray icon (minimal silhouette)",
    "neon star outline (simple 5-point)",
    "arcade coin icon (generic circle, no logos)",
    "ticket stub icon (generic)",
    "shopping bag silhouette (generic)",
    "mall directory sign silhouette (generic)",
    "pretzel/snack icon (generic, minimal)",
    "OPEN LATE emblem (generic typography)",
    "roller rink disco swirl (abstract)",
    "sparkly starburst (4-point sparkle)",
]

Y2K_SUPER_MOTIFS = [
    "CD disc abstract circle (no label rings)",
    "CD stack (generic, simplified)",
    "flip phone silhouette (generic)",
    "charging cable coil (generic)",
    "sparkle icon (simple 4-point)",
    "oval emblem (flat, no gradients)",
    "bubble text emblem (original typography)",
    "USB stick silhouette (generic)",
    "desktop tower side panel (generic)",
    "pixel flame icon (original grid design)",
]

AFTER_SCHOOL_TV_SUPER_MOTIFS = [
    "retro TV outline (box style, no logos)",
    "rabbit ear antenna silhouette",
    "remote control outline (generic)",
    "popcorn icon (original, minimal)",
    "rewind triangle icon (generic)",
    "couch silhouette (abstract, generic)",
    "TV guide-style grid icon (generic, simplified)",
]


# =========================
# Optional YAML drops.yaml support
# =========================
DROPS_YAML_PATH = os.getenv("DROPS_YAML", "drops.yaml")


def _load_yaml_config(path: str) -> Dict[str, Any]:
    if not yaml or not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_YAML: Dict[str, Any] = _load_yaml_config(DROPS_YAML_PATH)


def _yaml_list(key: str) -> List[str]:
    v = _YAML.get(key)
    if isinstance(v, list) and v:
        return [str(x) for x in v if str(x).strip()]
    return []


def _yaml_drops() -> List[Dict[str, Any]]:
    v = _YAML.get("drops")
    if isinstance(v, list) and v:
        return [d for d in v if isinstance(d, dict)]
    return []


def get_safe_phrases() -> List[str]:
    """
    Preferred accessor for phrase_engine and for YAML overrides.
    If drops.yaml defines safe_phrases, use it; else fallback to SAFE_PHRASES.
    """
    y = _yaml_list("safe_phrases")
    return y or list(SAFE_PHRASES)



def get_phrases(tier: str = "") -> List[str]:
    """Return phrases for the requested tier.

    Supported tiers:
      - safe (default)
      - edgy (still Shopify/Printify-safe; mild sarcasm, no slurs/harassment)
    You can override with drops.yaml keys:
      - safe_phrases
      - edgy_phrases
    """
    tier = (tier or os.getenv("PHRASE_TIER", "safe")).strip().lower()
    if tier == "edgy":
        v = _YAML.get("edgy_phrases") if isinstance(_YAML, dict) else None
        if isinstance(v, list) and v:
            return [str(x) for x in v]
        return list(EDGY_PHRASES)
    return get_safe_phrases()


DESIGN_MODES = [
    "icon_only",
    "text_only",
    "icon_plus_text",
    "monogram",
    "short_quote",
    "meme_phrase",
    "nostalgia_wordmark",
]

TEXT_MODES = [
    "single_word",
    "single_line",
    "stacked_two_line",
    "arched_with_icon",
    "block_monogram",
    "icon_above_word",
]

SLOGAN_BANK: Dict[str, List[str]] = {
    "dry_humor": ["LOW BATTERY", "SNACK BREAK", "USER BUSY", "LATE FEES", "ANALOG MOOD"],
    "faux_corporate": ["REWIND DEPT", "CACHE OFFICE", "HELP DESK 02", "NIGHT SHIFT", "STATUS BOARD"],
    "fake_club": ["AFTER SCHOOL CLUB", "CAMCORDER CREW", "MALL CERTIFIED", "RENTAL MEMBER", "ARCADE NIGHT"],
    "fake_department": ["BUFFER TEAM", "OFFLINE PROGRAM", "TAPE ARCHIVE", "DIAL TONE UNIT", "REPAIR DESK"],
    "status_phrases": ["OFFLINE TODAY", "DO NOT DISTURB", "PROBABLY BUFFERING", "SEEN ONLINE", "SIGNAL LOW"],
    "nostalgic_emotional": ["COUCH CAMP", "ANALOG HEART", "SLOW INTERNET", "HOME LAB", "RECESS ENERGY"],
    "old_tech": ["DIAL TONE", "LOADING FOREVER", "RENTAL COPY", "DISK SAVED", "CRT MODE"],
    "low_energy_meme": ["TOUCH GRASS LATER", "OUT OF OFFICE 1999", "BRB FOREVER", "MINIMUM EFFORT", "SOFT REBOOT"],
}

NOSTALGIA_AXES = ["80s_analog", "90s_mall", "2000s_internet", "arcade_night", "after_school_tv", "home_computer_lab"]

ICON_LIBRARY = [
    "cassette", "crt", "floppy", "cursor", "loading bar", "joystick", "snack cup", "arcade token",
    "tape stack", "remote", "cable box", "pager", "folder", "smiley badge", "note card", "mall sign",
    "pixel flame", "club stamp", "starburst", "receipt", "battery", "moon and star", "offline symbol",
]


def choose_slogan(*, humor_mode: str = "", slogan_type: str = "", max_chars: int = 20) -> str:
    modes = [slogan_type] if slogan_type in SLOGAN_BANK else list(SLOGAN_BANK.keys())
    if humor_mode == "deadpan":
        modes = ["dry_humor", "status_phrases", "nostalgic_emotional"] + modes
    pool: List[str] = []
    for m in modes:
        pool.extend(SLOGAN_BANK.get(m, []))
    pool = [p.strip().upper() for p in pool if p and len(p.strip()) <= max_chars and len(p.split()) <= 4]
    if not pool:
        pool = ["OFFLINE TODAY"]
    random.shuffle(pool)
    for item in pool:
        if not detect_risk(item):
            return item
    return "OFFLINE TODAY"


def pick_safe_phrase(include_text: bool = True) -> str:
    """Convenience: pick a phrase based on PHRASE_TIER."""
    if not include_text:
        return ""
    phrases = get_phrases(os.getenv("PHRASE_TIER", "safe"))
    return random.choice(phrases) if phrases else ""
def get_palette_hints() -> List[str]:
    y = _yaml_list("palette_hints")
    if y:
        return y
    # fallback
    return [
        "pastel mint + lavender",
        "teal + hot pink",
        "electric blue + neon yellow",
        "beige + forest green",
        "black + acid green",
        "washed denim blue + cream",
        "charcoal + pixel red",
        "dusty peach + sky blue",
    ]


def get_embroidery_styles() -> List[str]:
    y = _yaml_list("embroidery_styles")
    if y:
        return y
    return [
        "flat direct embroidery",
        "satin stitch bold fill",
        "fill-stitch geometric blocks",
        "front-center emblem scale",
        "compact icon mark",
    ]


def _default_drops() -> List[Dict[str, Any]]:
    # fallback if YAML not present
    return [
        {
            "name": "Analog Era",
            "slug": "analog-era",
            "limited": 500,
            "vibe": "retro tech minimal",
            "embroidery_focus": "bold center icon",
            "motifs": ANALOG_SUPER_MOTIFS,
        },
        {
            "name": "Playground Core",
            "slug": "playground-core",
            "limited": 500,
            "vibe": "recess nostalgia / carefree",
            "embroidery_focus": "single centered direct embroidery emblem",
            "motifs": PLAYGROUND_SUPER_MOTIFS,
        },
        {
            "name": "Early Internet",
            "slug": "early-internet",
            "limited": 500,
            "vibe": "dial-up / web 1.0 humor",
            "embroidery_focus": "minimal icon left chest or front",
            "motifs": INTERNET_SUPER_MOTIFS,
        },
        {
            "name": "Mall Culture",
            "slug": "mall-culture",
            "limited": 400,
            "vibe": "food court / arcade energy",
            "embroidery_focus": "bold puff embroidery",
            "motifs": MALL_SUPER_MOTIFS,
        },
        {
            "name": "After School TV",
            "slug": "after-school-tv",
            "limited": 400,
            "vibe": "couch + cartoons energy (non-IP)",
            "embroidery_focus": "small embroidered icon",
            "motifs": AFTER_SCHOOL_TV_SUPER_MOTIFS,
        },
        {
            "name": "Y2K Minimal",
            "slug": "y2k-minimal",
            "limited": 350,
            "vibe": "futuristic digital optimism (clean)",
            "embroidery_focus": "clean geometric thread blocks",
            "motifs": Y2K_SUPER_MOTIFS,
        },
    ]


def _drops() -> List[Dict[str, Any]]:
    yd = _yaml_drops()
    return yd or _default_drops()


def get_drop_names() -> List[str]:
    """Return drop slugs (stable)."""
    out: List[str] = []
    for d in _drops():
        slug = str(d.get("slug") or "").strip()
        name = str(d.get("name") or "").strip()
        if not slug and name:
            slug = slugify(name)
        if slug:
            out.append(slug)
    return out


def _match_drop(name_or_slug: str) -> Optional[Dict[str, Any]]:
    if not name_or_slug:
        return None
    key = slugify(name_or_slug)
    for d in _drops():
        slug = str(d.get("slug") or "").strip()
        nm = str(d.get("name") or "").strip()
        if slug and slugify(slug) == key:
            return d
        if nm and slugify(nm) == key:
            return d
    return None


def get_drop_meta(name_or_slug: str) -> Dict[str, Any]:
    d = _match_drop(name_or_slug) or {}
    if not isinstance(d, dict):
        return {}
    slug = str(d.get("slug") or "").strip() or slugify(str(d.get("name") or name_or_slug))
    title = str(d.get("name") or "").strip() or name_or_slug
    out = dict(d)
    out["slug"] = slug
    out["title"] = title
    return out


def get_drop_motifs(name_or_slug: str) -> List[str]:
    d = _match_drop(name_or_slug)
    if isinstance(d, dict):
        motifs = d.get("motifs") or []
        if isinstance(motifs, list) and motifs:
            return [str(x) for x in motifs if str(x).strip()]
    return []


def get_drop_limited(name_or_slug: str) -> int:
    d = _match_drop(name_or_slug)
    if isinstance(d, dict):
        try:
            return int(d.get("limited") or 0)
        except Exception:
            pass
    return int(os.getenv("LIMITED_RUN_DEFAULT", "500"))


def build_drop_tags(drop_slug_or_name: str) -> List[str]:
    meta = get_drop_meta(drop_slug_or_name)
    slug = _norm(str(meta.get("slug") or drop_slug_or_name))
    limited = get_drop_limited(slug)
    tags = [f"drop:{slug}", f"collection-handle:{slug}"]
    if limited:
        tags.append(f"limited:{limited}")
    return tags


# =========================
# Drop personality profiles (style/tone weighting)
# =========================
DROP_STYLE_WEIGHTS: Dict[str, List[Tuple[str, int]]] = {
    "analog-era": [("centered-emblem", 12), ("bold-icon-block", 10), ("monoline-symbol", 8), ("geometric-monogram", 6)],
    "playground-core": [("simplified-mascot-icon", 11), ("centered-emblem", 10), ("bold-icon-block", 8), ("direct-front-graphic", 6)],
    "early-internet": [("monoline-symbol", 11), ("geometric-monogram", 9), ("direct-front-graphic", 8), ("centered-emblem", 7)],
    "mall-culture": [("bold-icon-block", 10), ("centered-emblem", 9), ("framed-motif", 5), ("direct-front-graphic", 7)],
    "after-school-tv": [("centered-emblem", 11), ("simplified-mascot-icon", 8), ("direct-front-graphic", 8), ("monoline-symbol", 6)],
    "y2k-minimal": [("geometric-monogram", 10), ("monoline-symbol", 9), ("centered-emblem", 8), ("bold-icon-block", 6)],
}

DROP_TONE_WEIGHTS: Dict[str, List[Tuple[str, int]]] = {
    "analog-era": [
        ("raised offline pride", 10),
        ("premium understated nostalgia", 9),
        ("deadpan adult nostalgia", 6),
        ("calm retro tech minimalism", 7),
        ("subtle millennial humor", 5),
    ],
    "playground-core": [
        ("sleepover survivor energy", 9),
        ("analog childhood pride", 8),
        ("subtle millennial humor", 7),
        ("premium understated nostalgia", 6),
        ("deadpan adult nostalgia", 5),
    ],
    "early-internet": [
        ("light existential humor", 9),
        ("deadpan adult nostalgia", 8),
        ("subtle millennial humor", 7),
        ("premium understated nostalgia", 6),
        ("calm retro tech minimalism", 4),
    ],
    "mall-culture": [
        ("mall kid nostalgia", 10),
        ("subtle millennial humor", 8),
        ("deadpan adult nostalgia", 6),
        ("premium understated nostalgia", 5),
    ],
    "after-school-tv": [
        ("premium understated nostalgia", 8),
        ("sleepover survivor energy", 7),
        ("subtle millennial humor", 6),
        ("deadpan adult nostalgia", 5),
    ],
    "y2k-minimal": [
        ("calm retro tech minimalism", 8),
        ("premium understated nostalgia", 7),
        ("subtle millennial humor", 6),
        ("deadpan adult nostalgia", 5),
    ],
}


def pick_style_for_drop(drop_slug: str) -> str:
    weights = DROP_STYLE_WEIGHTS.get(_norm(drop_slug))
    if weights:
        return _pick_weighted(weights)
    return random.choice(STYLE_CHOICES)


def pick_tone_for_drop(drop_slug: str, *, edgy_mode: bool) -> str:
    base = DROP_TONE_WEIGHTS.get(_norm(drop_slug))
    if base:
        tone = _pick_weighted(base)
    else:
        tone = random.choice(TONE_LAYERS)

    if edgy_mode:
        # Blend in edgy tones sometimes (not always)
        if random.random() < 0.55:
            tone = random.choice(TONE_LAYERS + EDGY_TONES)
    return tone


def pick_phrase(*, edgy_mode: bool) -> str:
    # If user supplies custom phrase, keep that logic in phrase_engine; this is blueprint-side picker.
    phrases = get_safe_phrases()
    if edgy_mode:
        # weight edgy phrases higher but keep variety
        candidates = list(dict.fromkeys(phrases + EDGY_PHRASES + ADULT_MILLENNIAL_PHRASES))
        return random.choice(candidates)
    return random.choice(phrases)


# =========================
# Safety gate (lightweight)
# =========================
FORBIDDEN_TERMS = [
    # explicit media / entertainment / franchises
    "pokemon", "pikachu", "mario", "nintendo", "playstation", "xbox",
    "disney", "marvel", "dc", "simpsons", "spongebob", "looney tunes",
    "harry potter", "star wars", "jurassic park",
    # brands commonly referenced in nostalgia
    "nike", "adidas", "coca cola", "pepsi", "mtv", "nickelodeon", "sega",
    # slogan-ish phrases frequently trademarked
    "just do it", "think different", "i'm lovin",
]

# Phrase proximity guard (lightweight)
# We avoid phrases that are too close to famous slogans/taglines.
BANNED_SLOGANS = [
    "just do it",
    "think different",
    "im lovin it",
    "because youre worth it",
    "have it your way",
    "the ultimate driving machine",
    "finger lickin good",
]

def _norm_phrase(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s

def _too_close_to_slogan(s: str) -> Optional[str]:
    import difflib
    ns = _norm_phrase(s)
    if not ns:
        return None
    for ban in BANNED_SLOGANS:
        nb = _norm_phrase(ban)
        if not nb:
            continue
        if nb in ns:
            return f"Too close to known slogan: {ban!r}"
        ratio = difflib.SequenceMatcher(None, ns, nb).ratio()
        if ratio >= 0.88:
            return f"Too close to known slogan: {ban!r} (similarity={ratio:.2f})"
    return None
_FORBIDDEN_RE = re.compile(r"|".join(re.escape(t) for t in FORBIDDEN_TERMS), re.I)


def detect_risk(text: str) -> Optional[str]:
    """Return short reason if text matches a forbidden term or looks too close to a known slogan."""
    if not text:
        return None
    m = _FORBIDDEN_RE.search(text)
    if m:
        return f"Contains forbidden term: {m.group(0)!r}"
    # slogan proximity (mainly for phrases)
    close = _too_close_to_slogan(text)
    if close:
        return close
    return None


# =========================
# Design brief (Option B friendly)
# =========================
@dataclass
class DesignBrief:
    # Stable identifiers
    drop: str                 # slug for queue.csv
    drop_title: str = ""      # human display

    # Core creative
    motif: str = ""
    phrase: str = ""
    include_text: bool = False
    design_mode: str = "icon_only"
    text_mode: str = ""
    slogan_type: str = ""
    humor_mode: str = ""
    nostalgia_axis: str = ""
    wearable_score: str = ""
    novelty_score: str = ""
    nostalgia_score: str = ""
    clarity_score: str = ""
    embroidery_score: str = ""
    commercial_interest_reason: str = ""

    # Visual direction
    style: str = "centered-emblem"
    palette_hint: str = ""
    embroidery_style: str = ""
    embroidery_focus: str = ""
    vibe: str = ""
    tone: str = ""

    # Anti-repetition fields
    micro_niche: str = ""
    object_state: str = ""
    era_situation: str = ""
    texture_cue: str = ""
    variation_modifier: str = ""

    # Structured motif metadata for queue/debug
    motif_family: str = ""
    motif_frame: str = ""
    motif_keywords: str = ""
    center_weight: str = ""
    silhouette_strength: str = ""


def _pick_brief_raw(drop: Optional[str] = None, include_text: bool = False) -> DesignBrief:
    """
    V4 picker used at seed time (Option B).
    Returns a fully populated DesignBrief with anti-repetition fields.
    Store these values in queue.csv so the design is stable through human review.
    """
    edgy_mode = _env_true("EDGY_MODE", "0")

    chosen = drop or random.choice(get_drop_names())
    meta = get_drop_meta(chosen)
    drop_slug = str(meta.get("slug") or slugify(chosen))
    drop_title = str(meta.get("title") or chosen)

    motifs = get_drop_motifs(drop_slug) or get_drop_motifs(drop_title)
    if not motifs:
        motifs = ["memphis geometric emblem (triangles, squiggles, dots)"]

    palette_hint = random.choice(get_palette_hints()) if get_palette_hints() else ""
    emb_styles = get_embroidery_styles()
    embroidery_style = random.choice(emb_styles) if emb_styles else ""
    embroidery_focus = str(meta.get("embroidery_focus") or "")
    vibe = str(meta.get("vibe") or "")

    style = pick_style_for_drop(drop_slug)
    tone = pick_tone_for_drop(drop_slug, edgy_mode=edgy_mode)

    design_mode = _pick_weighted([
        ("icon_only", 23),
        ("text_only", 16),
        ("icon_plus_text", 26),
        ("monogram", 10),
        ("short_quote", 9),
        ("meme_phrase", 9),
        ("nostalgia_wordmark", 7),
    ])
    include_text = include_text or design_mode in ("text_only", "icon_plus_text", "short_quote", "meme_phrase", "nostalgia_wordmark")
    slogan_type = random.choice(list(SLOGAN_BANK.keys()))
    humor_mode = random.choice(["deadpan", "understated", "club_irony", "low_energy", "status_humor"])
    nostalgia_axis = random.choice(NOSTALGIA_AXES)
    text_mode_by_design = {
        "icon_only": "",
        "text_only": random.choice(["single_line", "stacked_two_line", "single_word"]),
        "icon_plus_text": random.choice(["icon_above_word", "arched_with_icon", "single_line"]),
        "monogram": "block_monogram",
        "short_quote": random.choice(["stacked_two_line", "single_line"]),
        "meme_phrase": random.choice(["single_line", "stacked_two_line"]),
        "nostalgia_wordmark": random.choice(["single_word", "single_line"]),
    }
    text_mode = text_mode_by_design.get(design_mode, "single_line")

    if include_text:
        phrase = choose_slogan(humor_mode=humor_mode, slogan_type=slogan_type, max_chars=22 if design_mode == "short_quote" else 20)
    else:
        phrase = ""

    motif_choices = motifs
    if design_mode in ("icon_only", "icon_plus_text"):
        motif_choices = motifs + [f"{random.choice(ICON_LIBRARY)} icon with thick silhouette"]
    if design_mode in ("text_only", "short_quote", "meme_phrase", "nostalgia_wordmark"):
        motif_choices = ["clean embroidery wordmark lockup", "short phrase typography lockup", "bold stitch-safe lettering"] + motif_choices

    wearable_score = str(random.randint(7, 10))
    novelty_score = str(random.randint(6, 10))
    nostalgia_score = str(random.randint(7, 10))
    clarity_score = str(random.randint(7, 10))
    embroidery_score = str(random.randint(8, 10))
    commercial_interest_reason = random.choice([
        "recognizable motif with wearable deadpan nostalgia",
        "short phrase with clear meme-adjacent status humor",
        "era-coded icon concept with strong center silhouette",
        "clean wordmark with subtle internet-native tone",
    ])

    return DesignBrief(
        drop=drop_slug,
        drop_title=drop_title,
        motif=random.choice(motif_choices),
        phrase=phrase,
        include_text=include_text,
        design_mode=design_mode,
        text_mode=text_mode,
        slogan_type=slogan_type,
        humor_mode=humor_mode,
        nostalgia_axis=nostalgia_axis,
        wearable_score=wearable_score,
        novelty_score=novelty_score,
        nostalgia_score=nostalgia_score,
        clarity_score=clarity_score,
        embroidery_score=embroidery_score,
        commercial_interest_reason=commercial_interest_reason,
        style=style,
        palette_hint=palette_hint,
        embroidery_style=embroidery_style,
        embroidery_focus=embroidery_focus,
        vibe=vibe,
        tone=tone,
        micro_niche=random.choice(MICRO_NICHES),
        object_state=random.choice(OBJECT_STATES),
        era_situation=random.choice(ERA_SITUATIONS),
        texture_cue=random.choice(TEXTURE_CUES),
        variation_modifier=random.choice(VARIATION_MODIFIERS),
        motif_family=random.choice(MOTIF_FAMILIES),
        motif_frame=random.choice(MOTIF_FRAMES),
        motif_keywords=", ".join(random.sample([
            "bold silhouette",
            "thick geometric stroke",
            "flat fill",
            "single emblem",
            "centered weight",
            "clean negative space",
            "direct embroidery",
            "vector clean edges",
        ], 3)),
        center_weight=random.choice(["strong", "strong", "medium"]),
        silhouette_strength=random.choice(["iconic", "iconic", "solid"]),
    )



# =========================
# Anti-repetition memory (seed-time)
# =========================
# Keeps recent picks from repeating: motif / micro_niche / era_situation / style / phrase
try:
    from memory_store import load_memory, save_memory, seen_recent, push  # type: ignore
except Exception:  # pragma: no cover
    load_memory = save_memory = seen_recent = push = None  # type: ignore


def pick_brief(drop: Optional[str] = None, include_text: bool = False) -> DesignBrief:
    """V4 picker (Option B) with anti-repetition memory.

    Wraps `_pick_brief_raw` with a small retry loop so large seeds feel diverse.
    Memory window + path are controlled via env:
      - MEMORY_PATH (default: recent_memory.json)
      - MEMORY_WINDOW (default: 50)
    """
    mem = None
    if load_memory:
        try:
            mem = load_memory()
        except Exception:
            mem = None

    last = None
    for _ in range(12):
        brief = _pick_brief_raw(drop=drop, include_text=include_text)
        last = brief
        if not mem or not seen_recent:
            break

        # Reject repeats on the most "feel-it" fields
        if seen_recent(mem, "motif", getattr(brief, "motif", "")):
            continue
        if seen_recent(mem, "micro_niche", getattr(brief, "micro_niche", "")):
            continue
        if seen_recent(mem, "era_situation", getattr(brief, "era_situation", "")):
            continue
        if seen_recent(mem, "style", getattr(brief, "style", "")):
            continue
        if include_text and seen_recent(mem, "phrase", getattr(brief, "phrase", "")):
            continue
        break

    brief = last or _pick_brief_raw(drop=drop, include_text=include_text)

    # Persist memory
    if mem is not None and push and save_memory:
        try:
            push(mem, {
                "motif": getattr(brief, "motif", ""),
                "micro_niche": getattr(brief, "micro_niche", ""),
                "era_situation": getattr(brief, "era_situation", ""),
                "style": getattr(brief, "style", ""),
                "phrase": getattr(brief, "phrase", "") if include_text else "",
            })
            save_memory(mem)
        except Exception:
            pass

    return brief

def brief_from_row(row: Dict[str, Any], *, include_text: bool) -> DesignBrief:
    """
    Convert a queue.csv row into a DesignBrief.
    This is useful at generate/publish time so prompts use stable, stored fields.
    """
    drop = (row.get("drop") or "").strip()
    drop_meta = get_drop_meta(drop) if drop else {}
    drop_title = (row.get("drop_title") or drop_meta.get("title") or "").strip()

    style = (row.get("style") or "centered-emblem").strip()
    if style not in STYLE_DIRECTIVES:
        style = "centered-emblem"

    return DesignBrief(
        drop=drop or str(drop_meta.get("slug") or ""),
        drop_title=drop_title or (drop_meta.get("title") or drop),
        motif=(row.get("motif") or "").strip(),
        phrase=(row.get("phrase") or "").strip(),
        include_text=include_text,
        design_mode=(row.get("design_mode") or "icon_only").strip(),
        text_mode=(row.get("text_mode") or "").strip(),
        slogan_type=(row.get("slogan_type") or "").strip(),
        humor_mode=(row.get("humor_mode") or "").strip(),
        nostalgia_axis=(row.get("nostalgia_axis") or "").strip(),
        wearable_score=(row.get("wearable_score") or "").strip(),
        novelty_score=(row.get("novelty_score") or "").strip(),
        nostalgia_score=(row.get("nostalgia_score") or "").strip(),
        clarity_score=(row.get("clarity_score") or "").strip(),
        embroidery_score=(row.get("embroidery_score") or "").strip(),
        commercial_interest_reason=(row.get("commercial_interest_reason") or "").strip(),
        style=style,
        palette_hint=(row.get("palette_hint") or "").strip(),
        embroidery_style=(row.get("embroidery_style") or "").strip(),
        embroidery_focus=(row.get("embroidery_focus") or "").strip(),
        vibe=(row.get("vibe") or "").strip(),
        tone=(row.get("tone") or "").strip(),
        micro_niche=(row.get("micro_niche") or "").strip(),
        object_state=(row.get("object_state") or "").strip(),
        era_situation=(row.get("era_situation") or "").strip(),
        texture_cue=(row.get("texture_cue") or "").strip(),
        variation_modifier=(row.get("variation_modifier") or "").strip(),
        motif_family=(row.get("motif_family") or "").strip(),
        motif_frame=(row.get("motif_frame") or "").strip(),
        motif_keywords=(row.get("motif_keywords") or "").strip(),
        center_weight=(row.get("center_weight") or "").strip(),
        silhouette_strength=(row.get("silhouette_strength") or "").strip(),
    )


def evaluate_embroidery_concept(brief: DesignBrief, *, product_type: str = "hat") -> Tuple[bool, List[str]]:
    """
    Returns (is_allowed, reasons).
    Blocks generation only for clearly invalid embroidery concepts.
    Non-blocking quality concerns are returned as risk_* reasons.
    """
    reasons: List[str] = []
    block_reasons: List[str] = []
    motif_text = " ".join([
        brief.motif,
        brief.motif_keywords,
        brief.variation_modifier,
        brief.texture_cue,
        brief.style,
        brief.palette_hint,
        brief.embroidery_style,
        brief.embroidery_focus,
        brief.phrase,
    ]).lower()

    # Hard-block only clearly invalid requests.
    if any(t in motif_text for t in ("gradient", "gradients", "ombre")):
        block_reasons.append("concept_blocked_gradient")

    if any(t in motif_text for t in ("photo", "photographic", "photoreal", "photorealistic", "realistic photo", "camera")):
        block_reasons.append("concept_blocked_photographic")

    if any(t in motif_text for t in ("thin line", "thin-line", "hairline", "micro detail", "micro-detail", "intricate linework", "ultra fine detail", "tiny detail")):
        block_reasons.append("concept_blocked_micro_detail")

    color_counts = [int(m.group(1)) for m in re.finditer(r"\b(\d{1,2})\s*(?:\+\s*)?(?:color|colors|colour|colours|thread|threads)\b", motif_text)]
    if color_counts and max(color_counts) > 6:
        block_reasons.append("concept_blocked_color_count_gt6")

    # Non-blocking quality concerns should trigger review, not immediate rejection.
    if any(t in motif_text for t in ("tiny text", "paragraph", "wallpaper", "landscape", "full scene")):
        reasons.append("risk_not_hat_compact")
    if brief.include_text and brief.phrase and len(brief.phrase) > 20:
        reasons.append("risk_text_too_long_for_embroidery")
    if brief.center_weight and brief.center_weight.lower() not in ("strong", "medium"):
        reasons.append("risk_weak_center_weight")
    if brief.silhouette_strength and brief.silhouette_strength.lower() not in ("iconic", "solid"):
        reasons.append("risk_weak_silhouette")
    if product_type == "hat" and brief.motif_family == "monogram" and brief.include_text and len(brief.phrase.split()) > 2:
        reasons.append("risk_monogram_text_too_complex")

    if brief.design_mode == "icon_only":
        weak_tokens = ("triangle", "circle", "oval", "dot", "abstract", "geometry")
        if not any(k in (brief.motif or "").lower() for k in ICON_LIBRARY) and sum(1 for t in weak_tokens if t in (brief.motif or "").lower()) >= 2:
            reasons.append("risk_generic_placeholder_geometry")

    try:
        ws = int(brief.wearable_score or 0)
        ns = int(brief.novelty_score or 0)
        cs = int(brief.clarity_score or 0)
        es = int(brief.embroidery_score or 0)
        if min(ws, ns, cs, es) < 6:
            reasons.append("risk_low_commercial_scores")
    except Exception:
        reasons.append("risk_scoring_missing")

    if not (brief.phrase or brief.motif):
        reasons.append("risk_missing_motif_or_phrase")

    reasons.extend(block_reasons)
    return (len(block_reasons) == 0, reasons)


# =========================
# Prompt builder (embroidery-tuned + V4 variety)
# =========================
def build_hat_prompt(brief: DesignBrief) -> str:
    return build_product_prompt(brief, product_type="hat")


def build_product_prompt(brief: DesignBrief, *, product_type: str = "hat") -> str:
    ptype = (product_type or "hat").strip().lower()
    style = brief.style if brief.style in STYLE_DIRECTIVES else "centered-emblem"
    style_desc = STYLE_DIRECTIVES.get(style, "")

    if brief.include_text and brief.phrase:
        idx = abs(hash((brief.drop, brief.phrase, brief.motif))) % max(1, len(TEXT_PAIRING_CONTEXTS))
        label_context = TEXT_PAIRING_CONTEXTS[idx]
        text_part = (
            f'Include the exact text "{brief.phrase}" in bold, clean block lettering as a {label_context} for direct front embroidery. '
            "Keep text large and short (1-3 words preferred)."
        )
    else:
        text_part = "No text. Icon-only with a recognizable motif people would wear."

    layout_guidance = {
        "single_line": "centered single-line wordmark",
        "stacked_two_line": "stacked two-line phrase with clear separation",
        "arched_with_icon": "arched top text with small centered icon",
        "block_monogram": "bold block monogram letters",
        "icon_above_word": "simple icon above short word",
        "single_word": "single short wordmark",
    }.get(brief.text_mode or "", "centered compact embroidery lockup")

    drop_name = brief.drop_title or brief.drop
    vibe_part = f"Vibe: {brief.vibe}. " if brief.vibe else ""
    tone_part = f"Emotional tone: {brief.tone}. " if brief.tone else ""
    emb_style = f"Embroidery style hint: {brief.embroidery_style}. " if brief.embroidery_style else ""
    emb_focus = f"Embroidery placement/focus: {brief.embroidery_focus}. " if brief.embroidery_focus else ""

    product_rules = PRODUCT_RULES.get(ptype, PRODUCT_RULES["hat"])
    cw, ch = product_rules["canvas_px"]
    sw, sh = product_rules["safe_in"]
    iw, ih = product_rules["size_in"]

    return (
        "Create an ORIGINAL, copyright-safe embroidery design. "
        f"Product type: {ptype}. "
        f"Artboard must be exactly {cw}x{ch}px at {product_rules['dpi']} DPI ({iw}in x {ih}in). "
        f"Design must be centered in the front panel safe area ({sw}in x {sh}in) with clear edge padding. "
        f"Collection: {drop_name}. {vibe_part}{tone_part}"
        f"Design mode: {brief.design_mode or 'icon_only'}. "
        f"Text mode: {brief.text_mode or 'none'}. Slogan type: {brief.slogan_type or 'none'}. Humor mode: {brief.humor_mode or 'understated'}. "
        f"Nostalgia axis: {brief.nostalgia_axis or '90s_mall'}. "
        f"Motif: {brief.motif}. Motif family: {brief.motif_family}. Frame: {brief.motif_frame}. "
        f"Motif keywords: {brief.motif_keywords}. "
        f"Center weight: {brief.center_weight or 'strong'}. Silhouette strength: {brief.silhouette_strength or 'iconic'}. "
        f"Color palette hint: {brief.palette_hint}. {emb_style}{emb_focus}"
        f"Layout archetype: {style}. {style_desc} "
        f"Typography/layout mode: {layout_guidance}. "
        f"Commercial intent: {brief.commercial_interest_reason or 'wearable, nostalgic, meme-adjacent'}; "
        f"scores(wearable={brief.wearable_score or '8'}, novelty={brief.novelty_score or '8'}, nostalgia={brief.nostalgia_score or '8'}, clarity={brief.clarity_score or '8'}, embroidery={brief.embroidery_score or '8'}). "
        f"Inspiration cues (not full scene): {brief.micro_niche}, {brief.era_situation}, {brief.object_state}, {brief.variation_modifier}. "
        f"{text_part} "
        "Embroidery production constraints: use only solid fills, maximum 6 thread colors selected from "
        f"{', '.join(EMBROIDERY_CONFIG.allowed_thread_palette)}. "
        "No gradients. No distressed texture. No photographic imagery. "
        "Strict style rules: flat vector icon, solid color fills, bold embroidery outlines, minimum 4px strokes, "
        "no texture, no grain, no shadow, no gradients, no shading, no distressed or vintage effects, "
        "direct embroidery front graphic, clean vector emblem, bold icon geometry, not patch illustration. "
        "Avoid transparent holes in center forms when possible. Avoid thin lines and tiny detail. "
        "Use bold iconic center-weighted shapes, thick strokes, and clean stitch-safe geometry. "
        "Single centered composition only; no background scene, no watermark, no signature."
    )
