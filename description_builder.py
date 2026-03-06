import os
from dotenv import load_dotenv

load_dotenv()

def build_description(title: str, niche: str = "", *, product_type: str = "hat", drop: str = "", motif: str = "", limited_count: int = 0) -> str:
    """
    Description structure:
    1) Emotional hook
    2) Nostalgia cue
    3) Generational identity (subtle)
    4) Quality specs
    5) Use cases
    """
    brand_line = os.getenv("BRAND_TAGLINE") or "Before filters. Before feeds. Before everything."
    drop_line = f"The {drop} collection pays tribute to growing up offline." if drop else "A subtle tribute to growing up offline."
    limited_env = os.getenv("LIMITED_RUN_DEFAULT", "500")
    if not limited_count:
        try:
            limited_count = int(limited_env)
        except Exception:
            limited_count = 0

    scarcity_line = ""
    if drop and limited_count:
        scarcity_line = f"Drop note: Limited run of {limited_count} for this release. When it’s gone, it’s gone."

    motif_line = f"Motif: {motif}." if motif else ""

    if product_type == "hat":
        return f"""
<h2>{title}</h2>

<p><em>{brand_line}</em></p>
<p>{drop_line}</p>
<p><strong>{scarcity_line}</strong></p>
<p>Minimal, collectible nostalgia—made for the ones who remember analog life.</p>

<p><strong>Details</strong></p>
<ul>
  <li>Embroidered front design (clean, durable stitching)</li>
  <li>Comfortable everyday fit (dad-hat style)</li>
  <li>Adjustable strap closure</li>
  <li>Made on demand and shipped to you</li>
</ul>

<p><strong>Wear it for:</strong> coffee runs, game days, weekend errands, and low-key nostalgia flex.</p>
<p style="font-size: 0.95em; opacity: 0.85;">{motif_line}</p>
""".strip()
    else:
        # fallback for future expansion
        return f"""
<h2>{title}</h2>
<p><em>{brand_line}</em></p>
<p>{drop_line}</p>
<p><strong>{scarcity_line}</strong></p>
<p style="font-size: 0.95em; opacity: 0.85;">{motif_line}</p>
""".strip()
