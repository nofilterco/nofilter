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


TYPOGRAPHY_MODES = [
    "bold_wordmark",
    "stacked_phrase",
    "arched_phrase",
    "retro_tech_mono",
    "varsity_block",
    "clean_sans_caps",
    "script_accent",
]

HAT_LAYOUT_TEMPLATES = [
    "single_line_center",
    "two_line_stack",
    "arched_top",
    "icon_above_text",
    "small_icon_left",
]

FONT_LIBRARY = {
    "varsity block": os.path.join("assets", "fonts", "Anton-Regular.ttf"),
    "condensed sans": os.path.join("assets", "fonts", "Montserrat-ExtraBold.ttf"),
    "bold grotesk": os.path.join("assets", "fonts", "Montserrat-Black.ttf"),
    "retro mono": os.path.join("assets", "fonts", "Montserrat-SemiBold.ttf"),
    "rounded sans": os.path.join("assets", "fonts", "Montserrat-Bold.ttf"),
    "simple script": os.path.join("assets", "fonts", "Montserrat-MediumItalic.ttf"),
}


def _pick_colors(rng: random.Random) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]:
    palette = [_hex_to_rgb(c) for c in EMBROIDERY_CONFIG.allowed_thread_palette]
    chosen = rng.sample(palette, k=min(4, len(palette)))
    return tuple(chosen[0]), tuple(chosen[1]), tuple(chosen[2]), tuple(chosen[3])


def _draw_icon(draw: ImageDraw.ImageDraw, motif: str, box: Tuple[int, int, int, int], colors, stroke: int) -> str:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    w, h = x1 - x0, y1 - y0
    c1, c2, c3, c4 = colors
    motif = motif.lower()

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


def _draw_typography_mode(draw: ImageDraw.ImageDraw, phrase: str, mode: str, area: Tuple[int, int, int, int], color: Tuple[int, int, int], rng: random.Random) -> Dict[str, str]:
    x0, y0, x1, y1 = area
    cx = (x0 + x1) // 2
    text = (phrase or "NO FILTER").strip().upper()[:28]
    tracking = 0
    font_key = "rounded sans"

    if mode == "varsity_block":
        font_key, tracking = "varsity block", 2
    elif mode == "retro_tech_mono":
        font_key, tracking = "retro mono", 1
    elif mode == "bold_wordmark":
        font_key, tracking = "bold grotesk", 1
    elif mode == "clean_sans_caps":
        font_key, tracking = "condensed sans", 2
    elif mode == "script_accent":
        font_key = "simple script"

    font = _fit_font(draw, text, area, FONT_LIBRARY[font_key], tracking=tracking)
    fill = color + (255,)

    if mode in ("stacked_phrase", "script_accent") and " " in text:
        lines = _split_phrase_for_stack(text)
        y = y0 + 12
        for ln in lines:
            ln_font = _fit_font(draw, ln, area, FONT_LIBRARY[font_key], start_size=78, min_size=34, tracking=tracking)
            w = _draw_spaced_text(draw, (0, 0), ln, ln_font, fill, tracking=tracking)
            draw_y = y
            draw_x = cx - w // 2
            _draw_spaced_text(draw, (draw_x, draw_y), ln, ln_font, fill, tracking=tracking)
            bb = draw.textbbox((draw_x, draw_y), ln, font=ln_font)
            y += (bb[3] - bb[1]) + 6
        return {"tracking": str(tracking), "stacked": "true"}

    if mode == "arched_phrase":
        step = 12
        radius = max(130, int((x1 - x0) * 0.26))
        center_y = y0 + int((y1 - y0) * 0.78)
        for idx, ch in enumerate(text):
            angle = (idx - (len(text) - 1) / 2) * step
            px = int(cx + radius * (angle / 90.0))
            py = int(center_y - (radius * 0.08) * ((angle / 28.0) ** 2))
            draw.text((px, py), ch, font=font, fill=fill)
        return {"tracking": "0", "stacked": "false", "arched": "true"}

    w = _draw_spaced_text(draw, (0, 0), text, font, fill, tracking=tracking)
    draw_x = cx - w // 2
    draw_y = y0 + max(0, ((y1 - y0) // 2) - (draw.textbbox((0, 0), text, font=font)[3] // 2))
    _draw_spaced_text(draw, (draw_x, draw_y), text, font, fill, tracking=tracking)
    return {"tracking": str(tracking), "stacked": "false"}


def _layout_boxes(layout: str, safe_x0: int, safe_y0: int, safe_x1: int, safe_y1: int) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]:
    icon_box = (safe_x0 + 360, safe_y0 + 24, safe_x1 - 360, safe_y0 + 170)
    text_box = (safe_x0 + 70, safe_y0 + 150, safe_x1 - 70, safe_y1 - 32)
    if layout == "single_line_center":
        text_box = (safe_x0 + 60, safe_y0 + 180, safe_x1 - 60, safe_y1 - 40)
    elif layout == "two_line_stack":
        text_box = (safe_x0 + 80, safe_y0 + 140, safe_x1 - 80, safe_y1 - 30)
    elif layout == "arched_top":
        text_box = (safe_x0 + 40, safe_y0 + 90, safe_x1 - 40, safe_y1 - 60)
    elif layout == "icon_above_text":
        icon_box = (safe_x0 + 430, safe_y0 + 24, safe_x1 - 430, safe_y0 + 160)
        text_box = (safe_x0 + 60, safe_y0 + 170, safe_x1 - 60, safe_y1 - 30)
    elif layout == "small_icon_left":
        icon_box = (safe_x0 + 90, safe_y0 + 190, safe_x0 + 220, safe_y0 + 320)
        text_box = (safe_x0 + 240, safe_y0 + 170, safe_x1 - 50, safe_y1 - 28)
    return icon_box, text_box


def _render_vector_hat_art(brief, resolved_style: str) -> Tuple[Image.Image, Dict[str, str]]:
    safe_x0 = (CANVAS_HAT[0] - HAT_SAFE_AREA[0]) // 2
    safe_y0 = (CANVAS_HAT[1] - HAT_SAFE_AREA[1]) // 2
    safe_x1 = safe_x0 + HAT_SAFE_AREA[0]
    safe_y1 = safe_y0 + HAT_SAFE_AREA[1]

    seed = abs(hash(f"{brief.drop}|{brief.motif}|{brief.phrase}|{resolved_style}|{getattr(brief, 'art_direction', '')}"))
    rng = random.Random(seed)

    phrase = (getattr(brief, "phrase", "") or "").strip().upper()
    requested_mode = (getattr(brief, "design_mode", "phrase_hat") or "phrase_hat").lower()
    design_mode = requested_mode if requested_mode in ("phrase_hat", "word_hat", "icon_phrase_hat") else "phrase_hat"
    if design_mode == "word_hat" and phrase:
        phrase = phrase.split()[0]
    if not phrase:
        phrase = "OFFLINE TODAY"

    typography_mode = random.choice(TYPOGRAPHY_MODES)
    layout = (getattr(brief, "layout_archetype", "") or "").strip().lower()
    if layout not in HAT_LAYOUT_TEMPLATES:
        layout = random.choice(HAT_LAYOUT_TEMPLATES)

    if design_mode == "icon_phrase_hat" and layout not in ("icon_above_text", "small_icon_left"):
        layout = random.choice(["icon_above_text", "small_icon_left"])
    if design_mode in ("phrase_hat", "word_hat") and layout in ("icon_above_text", "small_icon_left"):
        layout = random.choice(["single_line_center", "two_line_stack", "arched_top"])

    canvas = Image.new("RGBA", CANVAS_HAT, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    c1, c2, c3, c4 = _pick_colors(rng)
    stroke = max(6, int(CANVAS_HAT[0] * 0.0055))
    icon_box, text_box = _layout_boxes(layout, safe_x0, safe_y0, safe_x1, safe_y1)

    shape_quality = "none"
    icon_present = design_mode == "icon_phrase_hat"
    if icon_present:
        shape_quality = _draw_icon(draw, getattr(brief, "motif", ""), icon_box, (c1, c2, c3, c4), stroke)
        if shape_quality == "generic":
            icon_present = False
            shape_quality = "generic"

    typo_info = _draw_typography_mode(draw, phrase or "OFFLINE TODAY", typography_mode, text_box, c1, rng)
    shape_quality = "refined" if shape_quality not in ("generic", "none") else shape_quality

    safe_fill = (text_box[2] - text_box[0]) / float(HAT_SAFE_AREA[0])
    meta = {
        "composition_mode": f"{design_mode}_{layout}",
        "background_mode": "transparent",
        "frame_mode": "none",
        "safe_area_fill_pct": f"{safe_fill:.3f}",
        "motif_bbox": f"{icon_box[0]},{icon_box[1]},{icon_box[2]},{icon_box[3]}" if icon_present else "",
        "vector_mode_used": "true",
        "art_direction": getattr(brief, "art_direction", ""),
        "layout_archetype": layout,
        "type_treatment": typography_mode,
        "icon_treatment": getattr(brief, "icon_treatment", "clean_silhouette"),
        "frame_treatment": "none",
        "visual_energy": getattr(brief, "visual_energy", "balanced"),
        "commercial_style_reason": getattr(brief, "commercial_style_reason", ""),
        "plate_dependency": "low",
        "icon_present": "true" if icon_present else "false",
        "shape_quality": shape_quality,
        "letter_spacing": typo_info.get("tracking", "0"),
        "vertical_stacking": typo_info.get("stacked", "false"),
        "centered_layout": "true",
    }
    meta = _score_hat_design(meta, brief)

    if meta.get("commercial_reject_reasons"):
        return Image.new("RGBA", CANVAS_HAT, (0, 0, 0, 0)), {
            **meta,
            "rejected": "true",
            "composition_mode": f"rejected_{design_mode}",
        }
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
