from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path("out")
OUT_DIR.mkdir(exist_ok=True)

FONT_FILES = {
    "sans": "assets/fonts/Montserrat-Bold.ttf",
    "regular": "assets/fonts/Montserrat-Regular.ttf",
    "script": "assets/fonts/Montserrat-Italic.ttf",
    "mono": "assets/fonts/Montserrat-SemiBold.ttf",
}

SAFE_AREAS = {
    "tee": (0.16, 0.18, 0.68, 0.58),
    "hoodie": (0.15, 0.20, 0.70, 0.55),
    "crewneck": (0.15, 0.19, 0.70, 0.56),
    "mug": (0.08, 0.28, 0.84, 0.42),
    "tote": (0.14, 0.18, 0.72, 0.62),
}

MIN_FONT_BY_FAMILY = {"tee": 64, "hoodie": 68, "crewneck": 66, "mug": 54, "tote": 58}

STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "family-reunion": {
        "heritage": {"bg": (244, 235, 220, 255), "ink": (39, 60, 92, 255), "accent": (198, 86, 45, 255)},
        "sunset": {"bg": (255, 241, 231, 255), "ink": (47, 42, 67, 255), "accent": (220, 102, 81, 255)},
    },
    "wedding-bridal": {
        "blush": {"bg": (255, 243, 247, 255), "ink": (69, 38, 54, 255), "accent": (194, 95, 137, 255)},
        "champagne": {"bg": (255, 249, 238, 255), "ink": (71, 54, 40, 255), "accent": (178, 132, 84, 255)},
    },
    "bridal-party": {
        "violet": {"bg": (248, 245, 255, 255), "ink": (48, 43, 73, 255), "accent": (116, 90, 183, 255)},
        "night-out": {"bg": (238, 240, 255, 255), "ink": (36, 35, 68, 255), "accent": (236, 84, 146, 255)},
    },
    "family-milestones": {
        "classic": {"bg": (245, 241, 247, 255), "ink": (51, 45, 76, 255), "accent": (142, 97, 166, 255)},
        "modern": {"bg": (242, 246, 252, 255), "ink": (38, 50, 69, 255), "accent": (84, 122, 180, 255)},
    },
}

ICON_MAP = {"stars": "✦", "heart": "♥", "ring": "◌", "bow": "❦", "crest": "⬢", "laurel": "❧", "mug": "☕", "suitcase": "✈"}

TEMPLATE_FAMILY_ART_STRATEGY = {
    "text_only": "stacked_text",
    "monogram_badge": "monogram_frame",
    "text_plus_logo": "minimal_block",
    "text_plus_photo": "script_nameplate",
    "photo_keepsake": "script_nameplate",
    "wrap_mug": "wrap_mug",
}


def resolve_art_strategy(template_family: str, listing_slug: str = "", product_family: str = "") -> str:
    family = (template_family or "text_only").strip().lower()
    slug = (listing_slug or "").lower()
    product = (product_family or "").lower()
    if family == "text_only" and ("bride" in slug or "maid" in slug or "wedding" in slug):
        return "script_nameplate"
    if family == "text_only" and product in {"mug"}:
        return "stacked_text"
    if family == "text_plus_photo" and product == "mug":
        return "wrap_mug"
    return TEMPLATE_FAMILY_ART_STRATEGY.get(family, "stacked_text")


def default_placeholder_text(listing_slug: str, template_family: str) -> str:
    slug = (listing_slug or "").lower()
    family = (template_family or "text_only").lower()
    if "bridesmaid" in slug:
        return "Ava\nBridesmaid"
    if "maid-of-honor" in slug:
        return "Lily\nMaid of Honor"
    if "bride-crew" in slug:
        return "Bride Crew\nMiami 2026"
    if "groom-crew" in slug:
        return "Groom Crew\n2026"
    if "bach-weekend" in slug:
        return "Nashville\nBach Weekend"
    if "tote" in slug:
        return "Mia\nBridal Party Tote"
    if family == "monogram_badge":
        return "P\nWedding Crew"
    if family == "wrap_mug":
        return "Alex & Sam\n06.08.2026"
    return "Custom Name\nEst. 2026"


def _font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_FILES.get(name, FONT_FILES["sans"]), max(12, int(size)))
    except Exception:
        return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font_name: str, box: tuple[int, int], min_size: int, fill_ratio: float = 0.82) -> ImageFont.ImageFont:
    w, h = box
    size = int(min(w, h) * 0.45)
    while size > min_size:
        f = _font(font_name, size)
        bb = draw.multiline_textbbox((0, 0), text, font=f, spacing=max(4, size // 7), align="center")
        if (bb[2] - bb[0]) <= w * fill_ratio and (bb[3] - bb[1]) <= h * fill_ratio:
            return f
        size -= max(2, size // 12)
    return _font(font_name, min_size)


def _contrast_ink(blank: str, base_ink: tuple[int, int, int, int], contrast_mode: str = "auto") -> tuple[int, int, int, int]:
    dark_blanks = {"black", "navy", "maroon", "military green", "dark heather", "charcoal", "forest", "purple", "red"}
    mid_blanks = {"sport grey", "ash", "sand", "natural", "heather"}
    token = (blank or "").strip().lower()
    if contrast_mode == "light_on_dark" or (contrast_mode == "auto" and token in dark_blanks):
        return (252, 252, 252, 255)
    if contrast_mode == "auto" and token in mid_blanks:
        return (18, 18, 18, 255)
    return (25, 25, 25, 255) if contrast_mode in {"auto", "dark_on_light"} else base_ink


def _draw_icon(draw: ImageDraw.ImageDraw, icon: str, x: int, y: int, color: tuple[int, int, int, int], size: int) -> None:
    draw.text((x, y), ICON_MAP.get(icon, "✦"), font=_font("regular", size), fill=color)


def _resolve_preset(style_pack: str, collection_slug: str, slug: str) -> dict[str, int]:
    family = style_pack or collection_slug or "family-reunion"
    variant_pool = STYLE_PRESETS.get(family, STYLE_PRESETS["family-reunion"])
    variants = list(variant_pool.values())
    return variants[hash(slug) % len(variants)]


def build_placeholder_asset(text: str, slug: str, width: int = 1800, height: int = 2400, *, product_family: str = "tee", art_strategy: str = "stacked_text", collection_slug: str = "family-reunion", style_pack: str = "", contrast_mode: str = "auto", blank_color: str = "white", product_safe_area: dict[str, float] | None = None, icons: list[str] | None = None) -> str:
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    family = (product_family or "tee").lower()
    preset = _resolve_preset(style_pack, collection_slug, slug)

    sx, sy, sw, sh = SAFE_AREAS.get(family, SAFE_AREAS["tee"])
    family_tuning = {
        "hoodie": {"y": sy + 0.015, "h": sh - 0.03},
        "mug": {"x": sx - 0.01, "w": sw + 0.02},
        "tote": {"y": sy + 0.02, "h": sh - 0.02},
    }.get(family, {})
    sx = family_tuning.get("x", sx)
    sy = family_tuning.get("y", sy)
    sw = family_tuning.get("w", sw)
    sh = family_tuning.get("h", sh)
    if product_safe_area:
        sx, sy = product_safe_area.get("x", sx), product_safe_area.get("y", sy)
        sw, sh = product_safe_area.get("w", sw), product_safe_area.get("h", sh)

    safe = (int(width * sx), int(height * sy), int(width * (sx + sw)), int(height * (sy + sh)))
    box_w, box_h = safe[2] - safe[0], safe[3] - safe[1]
    min_font = MIN_FONT_BY_FAMILY.get(family, 52)

    ink, accent = _contrast_ink(blank_color, preset["ink"], contrast_mode), preset["accent"]
    text = (text or "Custom Name\nEst. 2026")[:120]
    strategy = (art_strategy or "stacked_text").lower()
    icons = icons or ["stars"]

    if strategy in {"stacked_text", "minimal_block"}:
        font = _fit_text(draw, text, "sans", (box_w, box_h), min_font, 0.86)
        bb = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=max(4, font.size // 7))
        tx, ty = safe[0] + (box_w - (bb[2] - bb[0])) // 2, safe[1] + (box_h - (bb[3] - bb[1])) // 2
        if strategy == "minimal_block":
            pad = int(font.size * 0.65)
            draw.rounded_rectangle((tx - pad, ty - pad, tx + (bb[2] - bb[0]) + pad, ty + (bb[3] - bb[1]) + pad), radius=22, fill=(*accent[:3], 40), outline=accent, width=5)
        draw.multiline_text((tx, ty), text, font=font, fill=ink, align="center", spacing=max(4, font.size // 7))
    elif strategy == "arch_badge":
        ring, cx, cy = min(box_w, box_h) // 2 - 18, safe[0] + box_w // 2, safe[1] + box_h // 2
        draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=accent, width=10)
        top, bottom = (text.split("\n") + ["REUNION"])[0], text.split("\n")[-1]
        f1 = _fit_text(draw, top, "mono", (int(box_w * 0.8), int(box_h * 0.20)), min_font - 8, 0.95)
        f2 = _fit_text(draw, bottom, "sans", (int(box_w * 0.75), int(box_h * 0.25)), min_font - 4, 0.95)
        draw.text((cx - draw.textlength(top, font=f1) // 2, cy - int(ring * 0.45)), top, font=f1, fill=ink)
        draw.text((cx - draw.textlength(bottom, font=f2) // 2, cy - int(ring * 0.05)), bottom, font=f2, fill=ink)
        _draw_icon(draw, icons[0], cx - 26, cy + int(ring * 0.34), accent, max(24, f1.size))
    elif strategy == "script_nameplate":
        font = _fit_text(draw, text, "script", (box_w, box_h), min_font - 6, 0.78)
        bb = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=max(3, font.size // 9))
        tx, ty = safe[0] + (box_w - (bb[2] - bb[0])) // 2, safe[1] + (box_h - (bb[3] - bb[1])) // 2
        yline = ty + (bb[3] - bb[1]) + int(font.size * 0.25)
        draw.line((safe[0] + int(box_w * 0.1), yline, safe[2] - int(box_w * 0.1), yline), fill=accent, width=6)
        draw.multiline_text((tx, ty), text, font=font, fill=ink, align="center")
    elif strategy == "monogram_frame":
        initial = "".join([p[:1].upper() for p in text.replace("\n", " ").split()[:2]]) or "CO"
        font = _fit_text(draw, initial, "mono", (int(box_w * 0.45), int(box_h * 0.45)), min_font, 0.9)
        cx, cy, frame = safe[0] + box_w // 2, safe[1] + box_h // 2, min(box_w, box_h) * 0.35
        draw.rectangle((cx - frame, cy - frame, cx + frame, cy + frame), outline=accent, width=9)
        draw.text((cx - draw.textlength(initial, font=font) // 2, cy - font.size // 2), initial, font=font, fill=ink)
        _draw_icon(draw, icons[0], int(cx - frame - 30), int(cy - frame - 34), accent, max(22, font.size // 3))
    else:  # wrap_mug + fallback
        band_h = int(box_h * 0.48)
        y1 = safe[1] + (box_h - band_h) // 2
        draw.rounded_rectangle((safe[0], y1, safe[2], y1 + band_h), radius=28, fill=(*accent[:3], 36), outline=accent, width=4)
        font = _fit_text(draw, text, "sans", (int(box_w * 0.88), int(band_h * 0.75)), min_font, 0.9)
        bb = draw.multiline_textbbox((0, 0), text, font=font, align="center")
        draw.multiline_text((safe[0] + (box_w - (bb[2] - bb[0])) // 2, y1 + (band_h - (bb[3] - bb[1])) // 2), text, font=font, fill=ink, align="center")
        _draw_icon(draw, "mug", safe[0] + 24, y1 + 18, accent, max(20, font.size // 4))

    path = OUT_DIR / f"placeholder_{slug}.png"
    img.save(path)
    return str(path)
