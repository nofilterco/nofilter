from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path("out")
OUT_DIR.mkdir(exist_ok=True)


def build_placeholder_asset(text: str, slug: str, width: int = 1800, height: int = 2400) -> str:
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("assets/fonts/Montserrat-Bold.ttf", 96)
    except Exception:
        font = ImageFont.load_default()
    safe_text = (text or "Custom Name")[:80]
    bbox = draw.multiline_textbbox((0, 0), safe_text, font=font, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = (height - th) // 2
    draw.multiline_text((x, y), safe_text, fill=(20, 20, 20, 255), font=font, align="center")
    path = OUT_DIR / f"placeholder_{slug}.png"
    img.save(path)
    return str(path)
