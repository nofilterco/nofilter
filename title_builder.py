import os
import random
from dotenv import load_dotenv
from typing import Optional

from drops import get_drop_names, get_drop_title

load_dotenv()

HAT_DESCRIPTORS = [
    "Embroidered Dad Hat",
    "Embroidered Cap",
    "Minimal Dad Hat",
    "Embroidered Low-Profile Hat",
]

PIN_DESCRIPTORS = [
    "Enamel Pin",
]

PATCH_DESCRIPTORS = [
    "Embroidered Patch",
]

def build_title(seed: str = "", *, product_type: str = "hat", drop: Optional[str] = None, motif_hint: Optional[str] = None) -> str:
    """
    Product title framework:
    Brand + Collection + Object + Descriptor + Audience
    Example:
      No Filter "Analog Era" Embroidered Dad Hat – 90s Minimal Nostalgia Cap
    """
    brand = (os.getenv("BRAND_NAME") or "No Filter").strip()
    drop = drop or random.choice(get_drop_names())
    drop = get_drop_title(drop)

    if product_type == "hat":
        desc = random.choice(HAT_DESCRIPTORS)
        extra = "90s Minimal Nostalgia"
        if motif_hint:
            # Keep motif hint subtle and generic
            extra = motif_hint.strip().title()
        return f'{brand} "{drop}" {desc} – {extra}'
    elif product_type == "pin":
        desc = random.choice(PIN_DESCRIPTORS)
        extra = "Retro 90s Minimal Accessory"
        if motif_hint:
            extra = motif_hint.strip().title()
        return f"{brand} {extra} {desc}"
    elif product_type == "patch":
        desc = random.choice(PATCH_DESCRIPTORS)
        extra = "Analog Era Badge"
        if motif_hint:
            extra = motif_hint.strip().title()
        return f'{brand} "{drop}" {desc} – {extra}'
    else:
        # fallback
        return f"{brand} {seed.title()}"

