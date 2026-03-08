import os
import random
import textwrap
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from openai_image import generate_image_pil
from nostalgia_blueprint import (
    EMBROIDERY_CONFIG,
    HAT_TEMPLATE,
    MAX_THREAD_COLORS,
    STYLE_DIRECTIVES,
    build_product_prompt,
    detect_risk,
    evaluate_embroidery_concept,
    pick_brief,
)

CANVAS_TEE = (4500, 5400)
CANVAS_HAT = (HAT_TEMPLATE["width_px"], HAT_TEMPLATE["height_px"])
HAT_SAFE_AREA = (1000, 550)

STRICT_EMBROIDERY_STYLE_RULES = (
    "direct embroidery graphic for hat front, clean vector emblem, flat embroidery-ready icon, "
    "satin-stitch-friendly shapes, fill-stitch-friendly blocks, thick geometric silhouette, transparent background, "
    "no patch backing, no label plate, no sticker layout, no faux thread texture, no grain, no shadow, no shading"
)


def _commercial_interest_ok(brief) -> bool:
    motif = (getattr(brief, "motif", "") or "").strip().lower()
    phrase = (getattr(brief, "phrase", "") or "").strip()
    design_mode = (getattr(brief, "design_mode", "phrase_hat") or "phrase_hat").strip().lower()
    if phrase and len(phrase) >= 3:
        return True
    if design_mode in ("icon_only", "icon_phrase_hat"):
        banned = ["triangle", "oval", "circle", "dot", "abstract", "geometry"]
        if sum(1 for b in banned if b in motif) >= 2:
            return False
    return len(motif) >= 6


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _closest_thread_color(rgb: Tuple[int, int, int], palette: List[Tuple[int, int, int]]) -> Tuple[int, int, int]:
    return min(palette, key=lambda p: (p[0] - rgb[0]) ** 2 + (p[1] - rgb[1]) ** 2 + (p[2] - rgb[2]) ** 2)


def _load_font(font_path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    if font_path and os.path.exists(font_path):
        return ImageFont.truetype(font_path, size=size)
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\impact.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def _wrap_lines(text: str, width: int = 18) -> List[str]:
    lines: List[str] = []
    for raw_line in (text or "").split("\n"):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        lines.extend(textwrap.wrap(raw_line, width=width))
    return lines if lines else [""]


def _center_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, box: Tuple[int, int, int, int], line_spacing: float = 1.05) -> None:
    x0, y0, x1, y1 = box
    lines = _wrap_lines(text, width=18)
    heights: List[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        heights.append(bbox[3] - bbox[1])
    total_h = int(sum(heights) * line_spacing)
    y = y0 + ((y1 - y0) - total_h) // 2
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = x0 + ((x1 - x0) - w) // 2
        draw.text((x, y), line, font=font, fill=(0, 0, 0, 255))
        y += int(h * line_spacing)


def _palette_restricted_quantize(img: Image.Image, *, preferred_colors: int = 5, hard_max: int = MAX_THREAD_COLORS) -> Tuple[Image.Image, int, int, List[str]]:
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    raw_colors = len((img.convert("RGB")).getcolors(maxcolors=1_000_000) or [])

    approved = [_hex_to_rgb(c) for c in EMBROIDERY_CONFIG.allowed_thread_palette]
    target = max(2, min(hard_max, preferred_colors))

    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img.convert("RGB"), mask=alpha)
    paletted = rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=target, dither=Image.Dither.NONE)
    sampled = [paletted.palette.palette[i:i + 3] for i in range(0, min(target * 3, len(paletted.palette.palette)), 3)]
    sampled_rgb = [tuple(s) for s in sampled if len(s) == 3]
    mapped = [_closest_thread_color(c, approved) for c in sampled_rgb] or approved[:target]

    mapped_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
    src = paletted.convert("RGB")
    spx = src.load()
    dpx = mapped_img.load()
    for y in range(img.height):
        for x in range(img.width):
            if alpha.getpixel((x, y)) <= 10:
                continue
            pix = spx[x, y]
            dpx[x, y] = _closest_thread_color(pix, mapped) + (255,)

    final_count = len((mapped_img.convert("RGB")).getcolors(maxcolors=1_000_000) or [])
    palette_used = ["#%02x%02x%02x" % c for c in sorted(set(mapped))[:hard_max]]
    return mapped_img, raw_colors, final_count, palette_used


def make_text_only(phrase: str, font_path: str) -> Image.Image:
    img = Image.new("RGBA", CANVAS_TEE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    phrase = (phrase or "").strip() or "NO FILTER"
    phrase = phrase.upper()
    size = 600
    box = (400, 1400, CANVAS_TEE[0] - 400, CANVAS_TEE[1] - 1800)
    while size > 120:
        font = _load_font(font_path, size)
        bbox = draw.multiline_textbbox((0, 0), phrase, font=font, spacing=20, align="center")
        if (bbox[2] - bbox[0]) <= (box[2] - box[0]):
            break
        size -= 20
    _center_text(draw, phrase, _load_font(font_path, size), box)
    return img


def make_ai_art(prompt: str, *, canvas: Tuple[int, int]) -> Image.Image:
    base = Image.new("RGBA", canvas, (0, 0, 0, 0))
    art = generate_image_pil(prompt).convert("RGBA")
    art = ImageOps.contain(art, (int(canvas[0] * 0.86), int(canvas[1] * 0.86)))
    x = (canvas[0] - art.size[0]) // 2
    y = (canvas[1] - art.size[1]) // 2
    base.paste(art, (x, y), mask=art.getchannel("A"))
    return base


def _commercial_quality_reasons(meta: Dict[str, str], brief) -> List[str]:
    reasons: List[str] = []
    phrase = (getattr(brief, "phrase", "") or "").strip()
    if not phrase or len(phrase.split()) > 4:
        reasons.append("weak_phrase")
    if meta.get("shape_quality") == "generic" and meta.get("icon_present") == "true":
        reasons.append("placeholder_geometry")
    if meta.get("plate_dependency", "low") != "low":
        reasons.append("plate_dependency")
    if int(meta.get("typography_quality_score", "0") or "0") < 7:
        reasons.append("typography_readability")
    return reasons


def _score_hat_design(meta: Dict[str, str], brief) -> Dict[str, str]:
    design_mode = (getattr(brief, "design_mode", "phrase_hat") or "phrase_hat").lower()
    phrase = (getattr(brief, "phrase", "") or "").strip()
    has_text = bool(phrase)
    has_icon = meta.get("icon_present", "false") == "true"

    hierarchy = 9
    balance = 8
    typo = 9 if has_text else 2
    icon_q = 8 if has_icon else 0

    if design_mode in ("phrase_hat", "word_hat") and has_icon:
        hierarchy -= 1
    if design_mode == "icon_phrase_hat" and not has_icon:
        hierarchy -= 3
    if not has_text:
        typo -= 6
        hierarchy -= 4
    if len(phrase) > 24 or len(phrase.split()) > 4:
        typo -= 2
    if meta.get("shape_quality") == "generic":
        icon_q -= 4
        balance -= 2
    if meta.get("plate_dependency") != "low":
        hierarchy -= 4
        balance -= 3
    if float(meta.get("safe_area_fill_pct", "0.7")) > 0.93:
        balance -= 2

    meta["hierarchy_score"] = str(max(1, min(10, hierarchy)))
    meta["visual_balance_score"] = str(max(1, min(10, balance)))
    meta["typography_quality_score"] = str(max(1, min(10, typo))) if has_text else ""
    meta["icon_quality_score"] = str(max(1, min(10, icon_q))) if has_icon else ""
    meta["commercial_reject_reasons"] = ",".join(_commercial_quality_reasons(meta, brief))
    return meta




def _draw_icon(draw: ImageDraw.ImageDraw, motif: str, box: Tuple[int, int, int, int], colors, stroke: int) -> str:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    w, h = x1 - x0, y1 - y0
    c1, c2, c3, c4 = colors
    motif = (motif or "").lower()

    if any(k in motif for k in ("cassette", "tape")):
        draw.rounded_rectangle(box, radius=int(h * 0.1), outline=c1 + (255,), width=stroke)
        draw.rounded_rectangle((x0 + int(w*0.12), y0 + int(h*0.26), x0 + int(w*0.36), y0 + int(h*0.62)), radius=7, fill=c2 + (255,))
        draw.rounded_rectangle((x1 - int(w*0.36), y0 + int(h*0.26), x1 - int(w*0.12), y0 + int(h*0.62)), radius=7, fill=c2 + (255,))
        return "stylized_cassette"
    if any(k in motif for k in ("loading", "buffer")):
        draw.rounded_rectangle(box, radius=int(h * 0.2), outline=c1 + (255,), width=stroke)
        sw = int(w * 0.15)
        sx = x0 + int(w * 0.1)
        for i in range(5):
            col = c2 if i < 3 else c4
            draw.rectangle((sx + i * sw, cy - int(h*0.12), sx + i * sw + sw - 5, cy + int(h*0.12)), fill=col + (255,))
        return "stylized_loading"
    if any(k in motif for k in ("cursor", "arrow")):
        draw.polygon([(x0 + int(w*0.2), y0 + int(h*0.08)), (x0 + int(w*0.72), cy), (x0 + int(w*0.42), cy + int(h*0.05)), (x0 + int(w*0.58), y1 - int(h*0.08)), (x0 + int(w*0.42), y1 - int(h*0.03)), (x0 + int(w*0.28), cy + int(h*0.2)), (x0 + int(w*0.2), cy + int(h*0.24))], fill=c1 + (255,))
        return "stylized_cursor"
    if "battery" in motif:
        draw.rounded_rectangle((x0, y0 + int(h*0.08), x1 - stroke*2, y1 - int(h*0.08)), radius=10, outline=c1 + (255,), width=stroke)
        draw.rectangle((x1 - stroke*2, cy - int(h*0.1), x1, cy + int(h*0.1)), fill=c1 + (255,))
        draw.rectangle((x0 + int(w*0.1), y0 + int(h*0.2), x0 + int(w*0.4), y1 - int(h*0.2)), fill=c2 + (255,))
        return "stylized_battery"
    if any(k in motif for k in ("joystick", "arcade")):
        draw.rounded_rectangle((x0 + int(w*0.08), y0 + int(h*0.52), x1 - int(w*0.08), y1), radius=16, outline=c1 + (255,), width=stroke)
        draw.ellipse((cx - int(w*0.09), y0 + int(h*0.1), cx + int(w*0.09), y0 + int(h*0.3)), fill=c2 + (255,))
        draw.rectangle((cx - int(w*0.02), y0 + int(h*0.28), cx + int(w*0.02), y0 + int(h*0.52)), fill=c2 + (255,))
        return "stylized_joystick"
    if "receipt" in motif:
        draw.rounded_rectangle(box, radius=8, outline=c1 + (255,), width=stroke)
        for i in range(3):
            yy = y0 + int(h * (0.25 + i * 0.2))
            draw.line((x0 + int(w*0.18), yy, x1 - int(w*0.18), yy), fill=c2 + (255,), width=max(3, stroke//2))
        return "stylized_receipt"
    if any(k in motif for k in ("signal", "pager")):
        draw.line((x0 + int(w*0.2), y1 - int(h*0.2), x0 + int(w*0.2), y0 + int(h*0.2)), fill=c1 + (255,), width=stroke)
        draw.arc((x0 + int(w*0.15), y0 + int(h*0.15), x0 + int(w*0.6), y1 - int(h*0.15)), 300, 60, fill=c2 + (255,), width=max(3, stroke//2))
        draw.arc((x0 + int(w*0.15), y0 + int(h*0.05), x0 + int(w*0.8), y1 - int(h*0.05)), 300, 60, fill=c2 + (255,), width=max(3, stroke//2))
        return "stylized_signal"
    if any(k in motif for k in ("moon", "star", "smiley", "pizza", "popcorn", "floppy", "crt")):
        draw.ellipse(box, outline=c1 + (255,), width=stroke)
        draw.ellipse((cx - int(w*0.1), cy - int(h*0.1), cx + int(w*0.1), cy + int(h*0.1)), fill=c2 + (255,))
        return "stylized_badge"
    return "generic"


def _split_phrase_for_stack(text: str) -> List[str]:
    words = text.split()
    if len(words) <= 1:
        return [text]
    if len(words) == 2:
        return words
    if len(words) == 3:
        return [" ".join(words[:2]), words[2]]
    return [" ".join(words[:2]), " ".join(words[2:])]


def _draw_spaced_text(draw: ImageDraw.ImageDraw, origin: Tuple[int, int], text: str, font: ImageFont.ImageFont, fill: Tuple[int, int, int, int], tracking: int = 0) -> int:
    x, y = origin
    cursor = x
    for ch in text:
        draw.text((cursor, y), ch, font=font, fill=fill, stroke_width=1, stroke_fill=fill)
        bb = draw.textbbox((cursor, y), ch, font=font)
        cursor += (bb[2] - bb[0]) + tracking
    return cursor - x


def _fit_font(draw: ImageDraw.ImageDraw, text: str, area: Tuple[int, int, int, int], font_path: str, start_size: int = 96, min_size: int = 36, tracking: int = 0) -> ImageFont.ImageFont:
    x0, _, x1, _ = area
    size = start_size
    while size >= min_size:
        font = _load_font(font_path, size)
        width = 0
        for ch in text:
            bb = draw.textbbox((0, 0), ch, font=font)
            width += (bb[2] - bb[0]) + tracking
        if width <= (x1 - x0):
            return font
        size -= 4
    return _load_font(font_path, min_size)

FONT_ROLES = {
    "headline_font": os.path.join("assets", "fonts", "Montserrat-Black.ttf"),
    "subheadline_font": os.path.join("assets", "fonts", "Montserrat-Bold.ttf"),
    "condensed_font": os.path.join("assets", "fonts", "Anton-Regular.ttf"),
    "mono_font": os.path.join("assets", "fonts", "Montserrat-SemiBold.ttf"),
    "varsity_font": os.path.join("assets", "fonts", "Anton-Regular.ttf"),
}

PALETTE_FAMILIES = {
    "navy_cream": {"primary": "#1c2a53", "secondary": "#f3ead5", "accent": "#c5b18a"},
    "forest_cream": {"primary": "#1e4a38", "secondary": "#f2ebd9", "accent": "#9dad7f"},
    "black_gold": {"primary": "#171717", "secondary": "#f2e7c9", "accent": "#c8a541"},
    "tan_brown": {"primary": "#ab835a", "secondary": "#513821", "accent": "#e2c8a0"},
    "red_white": {"primary": "#b3202e", "secondary": "#f7f3ee", "accent": "#18264f"},
    "maroon_gold": {"primary": "#65172b", "secondary": "#efdfb4", "accent": "#b59245"},
}

DESIGN_FAMILY_TO_TEMPLATES = {
    "wordmark": ["bold_single_line"],
    "stacked_phrase": ["stacked_two_line"],
    "club_mark": ["club_mark"],
    "service_mark": ["service_mark"],
    "retro_label": ["icon_above", "stacked_two_line"],
    "tech_status": ["icon_left", "bold_single_line"],
    "icon_with_caption": ["icon_left", "icon_above"],
}

LAYOUT_TEMPLATES = {
    "bold_single_line": {"text": "center", "icon": "none", "line_spacing": 1.0, "safe_padding": 60},
    "stacked_two_line": {"text": "stacked", "icon": "none", "line_spacing": 1.12, "safe_padding": 64},
    "club_mark": {"text": "stacked", "icon": "optional_top", "line_spacing": 1.1, "safe_padding": 54},
    "service_mark": {"text": "stacked", "icon": "optional_left", "line_spacing": 1.06, "safe_padding": 58},
    "icon_left": {"text": "center_left", "icon": "left", "line_spacing": 1.0, "safe_padding": 56},
    "icon_above": {"text": "center", "icon": "top", "line_spacing": 1.08, "safe_padding": 58},
}

TRACKING_VALUES = {"tight": -2, "normal": 0, "wide": 2}

TYPOGRAPHY_TEMPLATES = {
    "BIG_WORD": {
        "line_roles": ["condensed_font"],
        "size_weights": [1.0],
        "tracking": "tight",
        "line_spacing": 1.0,
        "alignment": "center",
    },
    "STACKED_TWO": {
        "line_roles": ["subheadline_font", "headline_font"],
        "size_weights": [0.8, 1.0],
        "tracking": "normal",
        "line_spacing": 0.9,
        "alignment": "center",
    },
    "STACKED_THREE": {
        "line_roles": ["subheadline_font", "headline_font", "subheadline_font"],
        "size_weights": [0.78, 1.0, 0.82],
        "tracking": "normal",
        "line_spacing": 0.88,
        "alignment": "center",
    },
    "SERVICE_MARK": {
        "line_roles": ["mono_font", "headline_font"],
        "size_weights": [0.76, 1.0],
        "tracking": "wide",
        "line_spacing": 0.95,
        "alignment": "center",
    },
    "CLUB_MARK": {
        "line_roles": ["varsity_font", "subheadline_font"],
        "size_weights": [1.0, 0.72],
        "tracking": "tight",
        "line_spacing": 0.9,
        "alignment": "center",
    },
    "SMALL_BIG_SMALL": {
        "line_roles": ["mono_font", "headline_font", "mono_font"],
        "size_weights": [0.72, 1.0, 0.72],
        "tracking": "wide",
        "line_spacing": 0.88,
        "alignment": "center",
    },
}

LEGACY_TO_TYPO_TEMPLATE = {
    "bold_single_line": "BIG_WORD",
    "stacked_two_line": "STACKED_TWO",
    "service_mark": "SERVICE_MARK",
    "club_mark": "CLUB_MARK",
    "icon_left": "SMALL_BIG_SMALL",
    "icon_above": "STACKED_THREE",
}

ICON_FAMILY_TO_MOTIF = {
    "cassette": "cassette",
    "battery": "battery",
    "cursor": "cursor",
    "loading bar": "loading_bar",
    "floppy": "floppy",
    "crt": "crt",
    "joystick": "joystick",
    "pager signal": "pager_signal",
    "arcade token": "arcade_token",
    "starburst": "starburst",
}


@dataclass
class TypographyLayout:
    lines: List[str]
    typography_template: str
    line_roles: List[str]
    line_weights: List[float]
    tracking_mode: str
    line_spacing: float
    alignment: str


def _pick_palette_family(name: str, rng: random.Random) -> Tuple[str, List[Tuple[int, int, int]]]:
    fam = name if name in PALETTE_FAMILIES else rng.choice(list(PALETTE_FAMILIES.keys()))
    p = PALETTE_FAMILIES[fam]
    return fam, [_hex_to_rgb(p[k]) for k in ("primary", "secondary", "accent")]


def _resolve_design_family(brief) -> str:
    family = (getattr(brief, "design_family", "") or "").strip().lower()
    return family if family in DESIGN_FAMILY_TO_TEMPLATES else "stacked_phrase"


def _resolve_template(brief, family: str, phrase: str) -> str:
    requested = (getattr(brief, "composition_template", "") or "").strip().lower()
    allowed = DESIGN_FAMILY_TO_TEMPLATES[family]
    if requested in allowed and requested in LAYOUT_TEMPLATES:
        return requested
    if len(phrase.split()) <= 1 and "bold_single_line" in allowed:
        return "bold_single_line"
    return allowed[0]


def _split_lines_for_template(phrase: str, template: str) -> List[str]:
    words = phrase.split()
    if not words:
        return [phrase]
    if template in ("BIG_WORD",):
        return [phrase]
    if template in ("SERVICE_MARK", "CLUB_MARK", "STACKED_TWO"):
        if len(words) == 1:
            return [phrase]
        if len(words) == 2:
            return [words[0], words[1]]
        mid = max(1, len(words) // 2)
        return [" ".join(words[:mid]), " ".join(words[mid:])]
    if template in ("STACKED_THREE", "SMALL_BIG_SMALL"):
        if len(words) <= 2:
            return words
        if len(words) == 3:
            return words
        return [words[0], " ".join(words[1:-1]), words[-1]]
    return [phrase]


def _classify_phrase(phrase: str) -> Dict[str, int]:
    txt = (phrase or "").strip()
    return {
        "word_count": len(txt.split()),
        "char_length": len(txt.replace(" ", "")),
    }


def _pick_typography_template(legacy_template: str, phrase: str) -> str:
    stats = _classify_phrase(phrase)
    word_count = stats["word_count"]
    char_length = stats["char_length"]
    forced = LEGACY_TO_TYPO_TEMPLATE.get(legacy_template, "")
    if forced in ("SERVICE_MARK", "CLUB_MARK"):
        return forced
    if word_count <= 1:
        return "BIG_WORD"
    if word_count == 2:
        return "STACKED_TWO"
    if word_count == 3:
        return "STACKED_THREE" if char_length < 16 else "SMALL_BIG_SMALL"
    return "SMALL_BIG_SMALL"


def _apply_phrase_emphasis(lines: List[str], phrase: str, rng: random.Random) -> List[float]:
    weights = [1.0 for _ in lines]
    if len(lines) <= 1:
        return weights
    boost_idx = max(range(len(lines)), key=lambda i: len(lines[i].replace(" ", "")))
    if rng.random() < 0.35:
        boost_idx = len(lines) - 1
    weights[boost_idx] = 1.15
    return weights


def _measure_with_tracking(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, tracking: int) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    width = bb[2] - bb[0]
    if hasattr(font, "getlength"):
        width = int(round(font.getlength(text)))
    return width + max(0, len(text) - 1) * tracking


def _draw_tracked_text(draw: ImageDraw.ImageDraw, origin: Tuple[int, int], text: str, font: ImageFont.ImageFont, fill: Tuple[int, int, int, int], tracking: int) -> int:
    x, y = origin
    cursor = x
    for i, ch in enumerate(text):
        draw.text((cursor, y), ch, font=font, fill=fill, stroke_width=1, stroke_fill=fill)
        bb = draw.textbbox((0, 0), ch, font=font)
        advance = bb[2] - bb[0]
        if hasattr(font, "getlength"):
            advance = int(round(font.getlength(ch)))
        cursor += advance + (tracking if i < len(text) - 1 else 0)
    return cursor - x


def _fit_font_size(draw: ImageDraw.ImageDraw, lines: List[str], text_box: Tuple[int, int, int, int], font_path: str, line_spacing: float, tracking: int, *, start: int = 132, min_size: int = 26) -> ImageFont.ImageFont:
    x0, y0, x1, y1 = text_box
    max_w = x1 - x0
    max_h = y1 - y0
    size = start
    while size >= min_size:
        font = _load_font(font_path, size)
        widths = [_measure_with_tracking(draw, line, font, tracking) for line in lines]
        line_h = draw.textbbox((0, 0), "Ag", font=font)[3]
        total_h = int(line_h * len(lines) * line_spacing)
        if max(widths) <= max_w and total_h <= max_h:
            return font
        size -= 2
    return _load_font(font_path, min_size)


def _layout_boxes(template: str, safe_x0: int, safe_y0: int, safe_x1: int, safe_y1: int):
    cfg = LAYOUT_TEMPLATES[template]
    pad = int(cfg["safe_padding"])
    text_box = (safe_x0 + pad, safe_y0 + pad, safe_x1 - pad, safe_y1 - pad)
    icon_box = (safe_x0 + 60, safe_y0 + 120, safe_x0 + 220, safe_y0 + 280)
    if template == "icon_left":
        icon_box = (safe_x0 + pad, safe_y0 + 150, safe_x0 + pad + 150, safe_y0 + 300)
        text_box = (icon_box[2] + 28, safe_y0 + 110, safe_x1 - pad, safe_y1 - 80)
    elif template == "icon_above":
        icon_box = (safe_x0 + 445, safe_y0 + 30, safe_x1 - 445, safe_y0 + 150)
        text_box = (safe_x0 + pad, safe_y0 + 175, safe_x1 - pad, safe_y1 - 45)
    elif template == "club_mark":
        icon_box = (safe_x0 + 455, safe_y0 + 45, safe_x1 - 455, safe_y0 + 145)
        text_box = (safe_x0 + pad, safe_y0 + 160, safe_x1 - pad, safe_y1 - 45)
    return icon_box, text_box


def _draw_icon_v2(draw: ImageDraw.ImageDraw, motif: str, box: Tuple[int, int, int, int], colors: Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]], stroke: int) -> str:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    w, h = x1 - x0, y1 - y0
    p, s, a = colors
    col_p, col_s, col_a = p + (255,), s + (255,), a + (255,)
    if motif == "cassette":
        draw.rounded_rectangle(box, radius=10, outline=col_p, width=stroke)
        draw.rectangle((x0 + w * 0.16, y0 + h * 0.32, x1 - w * 0.16, y0 + h * 0.48), fill=col_s)
    elif motif == "battery":
        draw.rounded_rectangle((x0, y0 + h * 0.08, x1 - stroke * 2, y1 - h * 0.08), radius=8, outline=col_p, width=stroke)
        draw.rectangle((x1 - stroke * 2, cy - h * 0.13, x1, cy + h * 0.13), fill=col_p)
        draw.rectangle((x0 + w * 0.12, y0 + h * 0.22, x0 + w * 0.45, y1 - h * 0.22), fill=col_s)
    elif motif == "cursor":
        draw.polygon([(x0 + w * 0.2, y0 + h * 0.08), (x0 + w * 0.74, cy), (x0 + w * 0.48, cy + h * 0.06), (x0 + w * 0.62, y1 - h * 0.08), (x0 + w * 0.46, y1 - h * 0.02), (x0 + w * 0.31, cy + h * 0.2), (x0 + w * 0.2, cy + h * 0.24)], fill=col_p)
    elif motif == "loading_bar":
        draw.rounded_rectangle(box, radius=10, outline=col_p, width=stroke)
        seg = int(w * 0.14)
        for i in range(5):
            color = col_s if i < 3 else col_a
            draw.rectangle((x0 + w * 0.1 + i * seg, y0 + h * 0.32, x0 + w * 0.1 + i * seg + seg - 5, y1 - h * 0.32), fill=color)
    elif motif == "floppy":
        draw.rectangle(box, outline=col_p, width=stroke)
        draw.rectangle((x0 + w * 0.12, y0 + h * 0.1, x1 - w * 0.12, y0 + h * 0.38), fill=col_s)
    elif motif == "crt":
        draw.rounded_rectangle((x0, y0 + h * 0.1, x1, y1 - h * 0.12), radius=12, outline=col_p, width=stroke)
        draw.rectangle((x0 + w * 0.12, y0 + h * 0.22, x1 - w * 0.12, y1 - h * 0.26), outline=col_s, width=max(2, stroke - 2))
    elif motif == "joystick":
        draw.rounded_rectangle((x0 + w * 0.08, y0 + h * 0.52, x1 - w * 0.08, y1), radius=14, outline=col_p, width=stroke)
        draw.ellipse((cx - w * 0.1, y0 + h * 0.1, cx + w * 0.1, y0 + h * 0.3), fill=col_s)
        draw.rectangle((cx - w * 0.025, y0 + h * 0.28, cx + w * 0.025, y0 + h * 0.52), fill=col_s)
    elif motif == "pager_signal":
        draw.rounded_rectangle((x0 + w * 0.12, y0 + h * 0.3, x1 - w * 0.12, y1), radius=8, outline=col_p, width=stroke)
        draw.line((cx, y0 + h * 0.08, cx, y0 + h * 0.3), fill=col_p, width=stroke)
    elif motif == "arcade_token":
        draw.ellipse(box, outline=col_p, width=stroke)
        draw.ellipse((x0 + w * 0.2, y0 + h * 0.2, x1 - w * 0.2, y1 - h * 0.2), outline=col_s, width=max(2, stroke - 2))
    elif motif == "starburst":
        points = [(cx, y0), (cx + w * 0.18, cy - h * 0.14), (x1, cy), (cx + w * 0.18, cy + h * 0.14), (cx, y1), (cx - w * 0.18, cy + h * 0.14), (x0, cy), (cx - w * 0.18, cy - h * 0.14)]
        draw.polygon(points, fill=col_s, outline=col_p)
    else:
        return "generic"
    return "refined"


def _draw_typography_v2(draw: ImageDraw.ImageDraw, phrase: str, text_box: Tuple[int, int, int, int], template: str, color: Tuple[int, int, int]) -> Dict[str, str]:
    phrase = (phrase or "OFFLINE TODAY").upper()
    typo_template = _pick_typography_template(template, phrase)
    cfg = TYPOGRAPHY_TEMPLATES[typo_template]
    lines = _split_lines_for_template(phrase, typo_template)
    rng = random.Random(abs(hash(phrase)))
    emphasis = _apply_phrase_emphasis(lines, phrase, rng)

    line_roles = list(cfg["line_roles"])
    while len(line_roles) < len(lines):
        line_roles.append(line_roles[-1])
    line_roles = line_roles[:len(lines)]

    base_weights = list(cfg["size_weights"])
    while len(base_weights) < len(lines):
        base_weights.append(base_weights[-1])
    base_weights = base_weights[:len(lines)]

    tracking_mode = cfg["tracking"]
    tracking = TRACKING_VALUES.get(tracking_mode, 0)
    spacing = float(cfg["line_spacing"])
    fill = color + (255,)
    x0, y0, x1, y1 = text_box
    max_w = x1 - x0
    max_h = y1 - y0
    min_letter_height = 38
    min_stroke_hint = 2

    target_fill = 0.75 if len(lines) == 1 else 0.7
    base_size = 140
    fonts: List[ImageFont.ImageFont] = []
    metrics = []
    while base_size >= min_letter_height:
        fonts = []
        metrics = []
        for idx, line in enumerate(lines):
            weight = base_weights[idx] * emphasis[idx]
            line_size = max(min_letter_height, int(base_size * weight))
            font = _load_font(FONT_ROLES[line_roles[idx]], line_size)
            ascent, descent = font.getmetrics()
            width = _measure_with_tracking(draw, line, font, tracking)
            metrics.append({"width": width, "ascent": ascent, "descent": descent, "height": ascent + descent})
            fonts.append(font)

        text_width = max(m["width"] for m in metrics)
        total_h = sum(m["height"] for m in metrics)
        total_h += int((len(lines) - 1) * (sum(m["height"] for m in metrics) / max(1, len(lines)) * spacing * 0.25))
        if text_width <= int(max_w * target_fill) and total_h <= max_h:
            break
        base_size -= 2

    total_h = sum(m["height"] for m in metrics)
    gap = int((sum(m["height"] for m in metrics) / max(1, len(lines))) * spacing * 0.25)
    total_h += gap * (len(lines) - 1)
    y = y0 + (max_h - total_h) // 2

    for idx, line in enumerate(lines):
        font = fonts[idx]
        m = metrics[idx]
        line_w = m["width"]
        x = x0 + (max_w - line_w) // 2
        baseline_y = y + m["ascent"]
        _draw_tracked_text(draw, (x, baseline_y - m["ascent"]), line, font, fill, tracking)
        y += m["height"] + gap

    return {
        "tracking": tracking_mode,
        "stacked": "true" if len(lines) > 1 else "false",
        "font_role": "/".join(line_roles),
        "line_count": str(len(lines)),
        "word_count": str(_classify_phrase(phrase)["word_count"]),
        "char_length": str(_classify_phrase(phrase)["char_length"]),
        "typography_template": typo_template,
        "min_letter_height_px": str(min_letter_height),
        "min_stroke_width_px": str(min_stroke_hint),
    }


def _validate_composition(phrase: str, template: str, icon_present: bool, icon_box: Tuple[int, int, int, int], text_box: Tuple[int, int, int, int]) -> List[str]:
    failures: List[str] = []
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    icon_area = max(1, (icon_box[2] - icon_box[0]) * (icon_box[3] - icon_box[1])) if icon_present else 0
    text_area = max(1, text_w * text_h)
    if text_w < int(HAT_SAFE_AREA[0] * 0.45):
        failures.append("visual_balance")
    if phrase and max(len(w) for w in phrase.split()) > 14:
        failures.append("text_readability")
    if icon_present and icon_area > int(text_area * 0.55):
        failures.append("icon_dominance")
    if template not in LAYOUT_TEMPLATES:
        failures.append("plate_dependency")
    return failures


def _apply_embroidery_rules(phrase: str, template: str, icon_present: bool) -> List[str]:
    rules: List[str] = []
    if phrase and len(phrase) <= 8 and template != "bold_single_line":
        rules.append("word_should_fill_area")
    if phrase and len(phrase.split()) <= 2 and template in ("icon_left", "icon_above") and not icon_present:
        rules.append("short_phrase_should_stack")
    if phrase and len(phrase) >= 18 and template == "bold_single_line":
        rules.append("long_phrase_should_wrap")
    return rules


def _render_vector_hat_art(brief, resolved_style: str) -> Tuple[Image.Image, Dict[str, str]]:
    safe_x0 = (CANVAS_HAT[0] - HAT_SAFE_AREA[0]) // 2
    safe_y0 = (CANVAS_HAT[1] - HAT_SAFE_AREA[1]) // 2
    safe_x1 = safe_x0 + HAT_SAFE_AREA[0]
    safe_y1 = safe_y0 + HAT_SAFE_AREA[1]

    seed = abs(hash(f"{brief.drop}|{brief.phrase}|{brief.design_family}|{brief.composition_template}|{brief.palette_family}"))
    rng = random.Random(seed)

    phrase = (getattr(brief, "phrase", "") or "OFFLINE TODAY").strip().upper()
    design_mode = (getattr(brief, "design_mode", "phrase_hat") or "phrase_hat").strip().lower()
    if design_mode not in ("phrase_hat", "word_hat", "icon_phrase_hat", "icon_only"):
        design_mode = "phrase_hat"
    if design_mode == "word_hat":
        phrase = phrase.split()[0] if phrase else "OFFLINE"

    family = _resolve_design_family(brief)
    template = _resolve_template(brief, family, phrase)
    if design_mode == "word_hat":
        template = "bold_single_line"
    if design_mode == "icon_phrase_hat" and template not in ("icon_left", "icon_above"):
        template = "icon_left"
    if len(phrase.split()) >= 4 and template == "bold_single_line":
        template = "stacked_two_line"

    palette_family, colors = _pick_palette_family((getattr(brief, "palette_family", "") or "").strip().lower(), rng)
    c1, c2, c3 = colors[:3]

    canvas = Image.new("RGBA", CANVAS_HAT, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    stroke = max(6, int(CANVAS_HAT[0] * 0.0055))
    icon_box, text_box = _layout_boxes(template, safe_x0, safe_y0, safe_x1, safe_y1)

    icon_family = (getattr(brief, "accent_icon_family", "none") or "none").strip().lower()
    motif = ICON_FAMILY_TO_MOTIF.get(icon_family, icon_family)
    icon_present = design_mode in ("icon_phrase_hat", "icon_only") and icon_family != "none"
    shape_quality = "none"
    if icon_present:
        shape_quality = _draw_icon_v2(draw, motif, icon_box, (c1, c2, c3), stroke)
        if shape_quality == "generic":
            icon_present = False
            if design_mode == "icon_only":
                design_mode = "phrase_hat"

    typo_info = {}
    if design_mode != "icon_only":
        typo_info = _draw_typography_v2(draw, phrase, text_box, template, c1)

    failures = _validate_composition(phrase, template, icon_present, icon_box, text_box)
    rule_flags = _apply_embroidery_rules(phrase, template, icon_present)
    safe_fill = (text_box[2] - text_box[0]) / float(HAT_SAFE_AREA[0])
    merch_taste = int(getattr(brief, "merch_taste_score", "8") or 8)

    layout_archetype = {
        "bold_single_line": "single_line_center",
        "stacked_two_line": "two_line_stack",
        "club_mark": "two_line_stack",
        "service_mark": "two_line_stack",
        "icon_left": "small_icon_left",
        "icon_above": "icon_above_text",
    }[template]

    meta = {
        "composition_mode": f"{design_mode}_{layout_archetype}",
        "composition_template": template,
        "background_mode": "transparent",
        "frame_mode": "none",
        "safe_area_fill_pct": f"{safe_fill:.3f}",
        "motif_bbox": f"{icon_box[0]},{icon_box[1]},{icon_box[2]},{icon_box[3]}" if icon_present else "",
        "vector_mode_used": "true",
        "layout_archetype": layout_archetype,
        "type_treatment": typo_info.get("font_role", ""),
        "icon_treatment": "accent_micro" if icon_present else "none",
        "visual_energy": "balanced",
        "plate_dependency": "low",
        "icon_present": "true" if icon_present else "false",
        "shape_quality": "refined" if shape_quality not in ("none", "generic") else shape_quality,
        "letter_spacing": typo_info.get("tracking", "0"),
        "vertical_stacking": typo_info.get("stacked", "false"),
        "typography_template": typo_info.get("typography_template", ""),
        "word_count": typo_info.get("word_count", ""),
        "char_length": typo_info.get("char_length", ""),
        "min_letter_height_px": typo_info.get("min_letter_height_px", ""),
        "min_stroke_width_px": typo_info.get("min_stroke_width_px", ""),
        "centered_layout": "true",
        "design_family": family,
        "slogan_family": str(getattr(brief, "slogan_family", "")),
        "font_pairing": str(getattr(brief, "font_pairing", "")),
        "palette_family": palette_family,
        "accent_icon_family": icon_family,
        "merch_style": str(getattr(brief, "merch_style", "")),
        "phrase_category": str(getattr(brief, "phrase_category", "")),
        "merch_taste_score": str(max(1, min(10, merch_taste))),
        "reroll_reason": str(getattr(brief, "reroll_reason", "")),
        "palette_used": ",".join([PALETTE_FAMILIES[palette_family]["primary"], PALETTE_FAMILIES[palette_family]["secondary"], PALETTE_FAMILIES[palette_family]["accent"]]),
    }

    meta = _score_hat_design(meta, brief)
    if int(meta.get("visual_balance_score", "8") or 8) < 6:
        meta["reroll_reason"] = "visual_balance_weak"
    if failures:
        meta["rejected"] = "true"
        meta["reroll_reason"] = "composition_failed_" + "_".join(sorted(set(failures)))
    if rule_flags and not meta.get("reroll_reason"):
        meta["reroll_reason"] = "embroidery_rules_" + "_".join(rule_flags)
    if rule_flags:
        meta["embroidery_rule_flags"] = ",".join(rule_flags)

    return canvas, meta


def build_design(
    style: str,
    title: str,
    phrase: str,
    niche: str,
    placement: str = "front",
    *,
    product_type: str = "hat",
    drop: Optional[str] = None,
    include_text: Optional[bool] = None,
    brief_context: Optional[dict] = None,
    validate_concept: bool = True,
    return_prompt: bool = False,
) -> Union[Image.Image, Tuple[Image.Image, str]]:
    style_in = (style or "ai_art").strip().lower()
    product_type = (product_type or "hat").strip().lower()
    for t in (title, phrase, niche):
        risk = detect_risk(t or "")
        if risk:
            raise ValueError(f"Blocked by safety gate: {risk}")

    if product_type == "hat":
        if include_text is None:
            include_text = True
        brief = pick_brief(drop=drop, include_text=bool(include_text))
        if brief_context and isinstance(brief_context, dict):
            for k, v in brief_context.items():
                if hasattr(brief, k) and v not in (None, ""):
                    setattr(brief, k, str(v))
        brief.phrase = phrase if include_text and phrase else (brief.phrase if include_text else "")

        resolved_style = style_in if style_in in STYLE_DIRECTIVES else getattr(brief, "style", "centered-emblem")
        if resolved_style not in STYLE_DIRECTIVES:
            resolved_style = "centered-emblem"
        brief.style = resolved_style

        if validate_concept:
            _, concept_reasons = evaluate_embroidery_concept(brief, product_type=product_type)
            blocked = [reason for reason in concept_reasons if reason.startswith("concept_blocked_")]
            if blocked:
                raise ValueError(f"Embroidery concept rejected: {','.join(blocked)}")

        if not _commercial_interest_ok(brief):
            raise ValueError("Embroidery concept rejected: commercial_interest_low")

        vector_first = (os.getenv("HAT_VECTOR_MODE", "1").strip().lower() in ("1", "true", "yes", "on"))
        prompt = build_product_prompt(brief, product_type=product_type)
        prompt = f"{prompt} Strict style rules: {STRICT_EMBROIDERY_STYLE_RULES}."

        if vector_first:
            img, meta = _render_vector_hat_art(brief, resolved_style)
            if meta.get("rejected") == "true":
                brief.design_mode = "phrase_hat"
                brief.layout_archetype = random.choice(["single_line_center", "two_line_stack", "arched_top"])
                img, meta = _render_vector_hat_art(brief, resolved_style)
        else:
            img = make_ai_art(prompt, canvas=CANVAS_HAT)
            meta = {
                "composition_mode": "single_line_center",
                "background_mode": "transparent",
                "frame_mode": "none",
                "vector_mode_used": "false",
                "safe_area_fill_pct": "0.800",
                "motif_bbox": "",
            }

        img, raw_count, final_count, palette_used = _palette_restricted_quantize(img, preferred_colors=5, hard_max=MAX_THREAD_COLORS)
        img.info.update(meta)
        img.info["raw_color_count"] = str(raw_count)
        img.info["final_color_count"] = str(final_count)
        img.info["palette_used"] = ",".join(palette_used)
        img.info["dpi"] = (HAT_TEMPLATE["dpi"], HAT_TEMPLATE["dpi"])

        if return_prompt:
            return img, prompt
        return img

    fonts = [os.path.join("assets", "fonts", "Anton-Regular.ttf"), os.path.join("assets", "fonts", "Montserrat-Bold.ttf")]
    font_path = random.choice(fonts)
    if style_in == "mix":
        style_in = random.choices(["text", "ai_art"], weights=[25, 75])[0]
    if style_in == "text":
        return make_text_only(phrase, font_path)

    prompt = (
        f"Professional high-detail t-shirt graphic inspired by {niche}. "
        "Single large central subject, bold silhouette, strong contrast, clean edges, "
        f"vector/screenprint style, transparent background, no text, no watermark. Style rules: {STRICT_EMBROIDERY_STYLE_RULES}."
    )
    img = make_ai_art(prompt, canvas=CANVAS_TEE)
    if return_prompt:
        return img, prompt
    return img
