import os
import random
import textwrap
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
        draw.text((cursor, y), ch, font=font, fill=fill)
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
    "bold_sans": os.path.join("assets", "fonts", "Montserrat-Black.ttf"),
    "condensed_caps": os.path.join("assets", "fonts", "Anton-Regular.ttf"),
    "varsity_block": os.path.join("assets", "fonts", "Anton-Regular.ttf"),
    "retro_mono": os.path.join("assets", "fonts", "Montserrat-SemiBold.ttf"),
    "understated_caps": os.path.join("assets", "fonts", "Montserrat-Bold.ttf"),
    "soft_script_accent": os.path.join("assets", "fonts", "Montserrat-MediumItalic.ttf"),
}

PALETTE_FAMILIES = {
    "cream_green_red": ["#ffffff", "#01784e", "#cc3333"],
    "navy_cream": ["#333366", "#ffffff", "#96a1a8"],
    "black_cream": ["#000000", "#ffffff", "#a67843"],
    "tan_brown_red": ["#a67843", "#660000", "#e25c27"],
    "white_red_blue": ["#ffffff", "#cc3333", "#005397"],
    "forest_cream": ["#01784e", "#ffffff", "#7ba35a"],
    "slate_cream": ["#96a1a8", "#ffffff", "#333366"],
    "maroon_gold": ["#660000", "#ffcc00", "#a67843"],
    "vintage_blue_cream": ["#005397", "#3399ff", "#ffffff"],
}

TEMPLATE_CONFIG = {
    "bold_single_line": {"layout": "single_line_center", "max_words": 3, "font_roles": ["condensed_caps", "understated_caps"], "icon": "none"},
    "stacked_two_line": {"layout": "two_line_stack", "max_words": 4, "font_roles": ["bold_sans", "understated_caps"], "icon": "optional"},
    "small_caps_service_mark": {"layout": "single_line_center", "max_words": 4, "font_roles": ["understated_caps", "retro_mono"], "icon": "optional"},
    "faux_department_lockup": {"layout": "two_line_stack", "max_words": 4, "font_roles": ["varsity_block", "understated_caps"], "icon": "optional"},
    "varsity_wordmark": {"layout": "single_line_center", "max_words": 2, "font_roles": ["varsity_block", "understated_caps"], "icon": "none"},
    "retro_tech_wordmark": {"layout": "single_line_center", "max_words": 3, "font_roles": ["retro_mono", "bold_sans"], "icon": "optional"},
    "icon_accent_left": {"layout": "small_icon_left", "max_words": 4, "font_roles": ["bold_sans", "understated_caps"], "icon": "required"},
    "icon_accent_top": {"layout": "icon_above_text", "max_words": 4, "font_roles": ["condensed_caps", "understated_caps"], "icon": "required"},
    "monogram_subtitle": {"layout": "arched_top", "max_words": 3, "font_roles": ["condensed_caps", "retro_mono"], "icon": "none"},
    "club_mark": {"layout": "two_line_stack", "max_words": 4, "font_roles": ["varsity_block", "retro_mono"], "icon": "optional"},
}

ICON_FAMILY_TO_MOTIF = {
    "cassette": "cassette", "loading bar": "loading", "cursor": "cursor", "battery": "battery",
    "floppy": "floppy", "crt": "crt", "joystick": "joystick", "popcorn": "popcorn",
    "pizza slice": "pizza", "smiley": "smiley", "moon/star": "moon", "arcade token": "arcade",
    "receipt": "receipt", "pager signal": "signal",
}


def _pick_palette_family(name: str, rng: random.Random) -> Tuple[str, List[Tuple[int, int, int]]]:
    fam = name if name in PALETTE_FAMILIES else rng.choice(list(PALETTE_FAMILIES.keys()))
    return fam, [_hex_to_rgb(c) for c in PALETTE_FAMILIES[fam][:4]]


def _fit_phrase_for_template(phrase: str, template: str) -> Tuple[str, bool]:
    cfg = TEMPLATE_CONFIG.get(template, TEMPLATE_CONFIG["bold_single_line"])
    words = phrase.split()
    if len(words) <= cfg["max_words"]:
        return phrase, True
    short = " ".join(words[: cfg["max_words"]])
    return short, False


def _draw_typography_template(draw: ImageDraw.ImageDraw, phrase: str, text_box: Tuple[int, int, int, int], template: str, color: Tuple[int, int, int]) -> Dict[str, str]:
    cfg = TEMPLATE_CONFIG.get(template, TEMPLATE_CONFIG["bold_single_line"])
    primary_role = cfg["font_roles"][0]
    font_path = FONT_ROLES[primary_role]
    text = (phrase or "OFFLINE TODAY").strip().upper()

    x0, y0, x1, y1 = text_box
    cx = (x0 + x1) // 2
    fill = color + (255,)
    tracking = 1 if primary_role in ("condensed_caps", "varsity_block") else 0

    if template in ("stacked_two_line", "faux_department_lockup", "club_mark") and " " in text:
        lines = _split_phrase_for_stack(text)
        y = y0 + 8
        used = "true"
        for ln in lines:
            font = _fit_font(draw, ln, text_box, font_path, start_size=92, min_size=34, tracking=tracking)
            w = _draw_spaced_text(draw, (0, 0), ln, font, fill, tracking=tracking)
            _draw_spaced_text(draw, (cx - w // 2, y), ln, font, fill, tracking=tracking)
            bb = draw.textbbox((0, 0), ln, font=font)
            y += (bb[3] - bb[1]) + 6
        return {"tracking": str(tracking), "stacked": used, "font_role": primary_role}

    font = _fit_font(draw, text, text_box, font_path, start_size=104, min_size=34, tracking=tracking)
    w = _draw_spaced_text(draw, (0, 0), text, font, fill, tracking=tracking)
    bb = draw.textbbox((0, 0), text, font=font)
    draw_y = y0 + max(0, ((y1 - y0) - (bb[3] - bb[1])) // 2)
    _draw_spaced_text(draw, (cx - w // 2, draw_y), text, font, fill, tracking=tracking)
    return {"tracking": str(tracking), "stacked": "false", "font_role": primary_role}


def _layout_boxes(layout: str, safe_x0: int, safe_y0: int, safe_x1: int, safe_y1: int) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]:
    icon_box = (safe_x0 + 360, safe_y0 + 24, safe_x1 - 360, safe_y0 + 170)
    text_box = (safe_x0 + 70, safe_y0 + 150, safe_x1 - 70, safe_y1 - 32)
    if layout == "single_line_center":
        text_box = (safe_x0 + 60, safe_y0 + 190, safe_x1 - 60, safe_y1 - 45)
    elif layout == "two_line_stack":
        text_box = (safe_x0 + 80, safe_y0 + 130, safe_x1 - 80, safe_y1 - 30)
    elif layout == "arched_top":
        text_box = (safe_x0 + 40, safe_y0 + 95, safe_x1 - 40, safe_y1 - 65)
    elif layout == "icon_above_text":
        icon_box = (safe_x0 + 450, safe_y0 + 24, safe_x1 - 450, safe_y0 + 150)
        text_box = (safe_x0 + 60, safe_y0 + 165, safe_x1 - 60, safe_y1 - 30)
    elif layout == "small_icon_left":
        icon_box = (safe_x0 + 85, safe_y0 + 185, safe_x0 + 220, safe_y0 + 320)
        text_box = (safe_x0 + 245, safe_y0 + 170, safe_x1 - 45, safe_y1 - 28)
    return icon_box, text_box


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

    template = (getattr(brief, "composition_template", "") or "bold_single_line").strip().lower()
    if template not in TEMPLATE_CONFIG:
        template = "icon_accent_left" if design_mode == "icon_phrase_hat" else "bold_single_line"

    phrase, fits_template = _fit_phrase_for_template(phrase, template)
    if not fits_template and design_mode != "icon_only":
        template = "stacked_two_line"

    layout = TEMPLATE_CONFIG.get(template, TEMPLATE_CONFIG["bold_single_line"])["layout"]
    icon_expected = TEMPLATE_CONFIG.get(template, {}).get("icon")
    if design_mode == "icon_phrase_hat" and icon_expected == "none":
        template = "icon_accent_left"
        layout = "small_icon_left"

    palette_family, colors = _pick_palette_family((getattr(brief, "palette_family", "") or "").strip().lower(), rng)
    c1, c2, c3 = colors[:3]

    canvas = Image.new("RGBA", CANVAS_HAT, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    stroke = max(6, int(CANVAS_HAT[0] * 0.0055))
    icon_box, text_box = _layout_boxes(layout, safe_x0, safe_y0, safe_x1, safe_y1)

    icon_family = (getattr(brief, "accent_icon_family", "none") or "none").strip().lower()
    motif = ICON_FAMILY_TO_MOTIF.get(icon_family, icon_family)
    icon_present = design_mode in ("icon_phrase_hat", "icon_only") and icon_family != "none"
    shape_quality = "none"
    if icon_present:
        shape_quality = _draw_icon(draw, motif, icon_box, (c1, c2, c3, c1), stroke)
        if shape_quality == "generic":
            icon_present = False
            if design_mode == "icon_only":
                design_mode = "phrase_hat"

    typo_info = {}
    if design_mode != "icon_only":
        typo_info = _draw_typography_template(draw, phrase, text_box, template, c1)

    safe_fill = (text_box[2] - text_box[0]) / float(HAT_SAFE_AREA[0])
    merch_taste = int(getattr(brief, "merch_taste_score", "8") or 8)
    if shape_quality == "generic":
        merch_taste = max(5, merch_taste - 2)

    meta = {
        "composition_mode": f"{design_mode}_{layout}",
        "composition_template": template,
        "background_mode": "transparent",
        "frame_mode": "none",
        "safe_area_fill_pct": f"{safe_fill:.3f}",
        "motif_bbox": f"{icon_box[0]},{icon_box[1]},{icon_box[2]},{icon_box[3]}" if icon_present else "",
        "vector_mode_used": "true",
        "layout_archetype": layout,
        "type_treatment": typo_info.get("font_role", ""),
        "icon_treatment": "accent_micro" if icon_present else "none",
        "visual_energy": "balanced",
        "plate_dependency": "low",
        "icon_present": "true" if icon_present else "false",
        "shape_quality": "refined" if shape_quality not in ("none", "generic") else shape_quality,
        "letter_spacing": typo_info.get("tracking", "0"),
        "vertical_stacking": typo_info.get("stacked", "false"),
        "centered_layout": "true",
        "design_family": str(getattr(brief, "design_family", "text_first")),
        "slogan_family": str(getattr(brief, "slogan_family", "")),
        "font_pairing": str(getattr(brief, "font_pairing", "")),
        "palette_family": palette_family,
        "accent_icon_family": icon_family,
        "merch_style": str(getattr(brief, "merch_style", "")),
        "phrase_category": str(getattr(brief, "phrase_category", "")),
        "merch_taste_score": str(max(1, min(10, merch_taste))),
        "reroll_reason": str(getattr(brief, "reroll_reason", "")),
        "palette_used": ",".join(PALETTE_FAMILIES[palette_family]),
    }

    meta = _score_hat_design(meta, brief)
    if int(meta.get("typography_quality_score", "8") or 8) < 6 and design_mode != "icon_only":
        meta["reroll_reason"] = "typography_weak"
    if int(meta.get("visual_balance_score", "8") or 8) < 6:
        meta["reroll_reason"] = "visual_balance_weak"

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
