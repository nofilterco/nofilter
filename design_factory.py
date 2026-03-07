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
    design_mode = (getattr(brief, "design_mode", "icon_only") or "icon_only").strip().lower()
    if phrase and len(phrase) >= 3:
        return True
    if design_mode == "icon_only":
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


def _score_hat_design(meta: Dict[str, str], brief) -> Dict[str, str]:
    design_mode = (getattr(brief, "design_mode", "icon_only") or "icon_only").lower()
    has_text = bool(getattr(brief, "include_text", False) and getattr(brief, "phrase", ""))
    has_icon = meta.get("icon_present", "true") == "true"
    plate_dependency = meta.get("plate_dependency", "low")

    hierarchy = 8
    balance = 8
    typo = 8 if has_text else 0
    icon_q = 8 if has_icon else 0

    if design_mode == "text_only" and not has_text:
        hierarchy -= 4
        typo -= 5
    if design_mode == "icon_only" and not has_icon:
        hierarchy -= 4
        icon_q -= 5
    if design_mode == "icon_plus_text" and not (has_text and has_icon):
        hierarchy -= 3
        balance -= 2
    if plate_dependency != "low":
        hierarchy -= 3
        balance -= 3
    if meta.get("frame_mode") == "none" and design_mode == "icon_only" and meta.get("shape_quality") == "generic":
        icon_q -= 3

    meta["hierarchy_score"] = str(max(1, min(10, hierarchy)))
    meta["visual_balance_score"] = str(max(1, min(10, balance)))
    meta["typography_quality_score"] = str(max(1, min(10, typo))) if has_text else ""
    meta["icon_quality_score"] = str(max(1, min(10, icon_q))) if has_icon else ""
    meta["plate_dependency"] = plate_dependency
    return meta


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
        draw.rounded_rectangle(box, radius=int(h * 0.12), outline=c1 + (255,), width=stroke)
        draw.rounded_rectangle((x0 + int(w*0.1), y0 + int(h*0.25), x0 + int(w*0.36), y0 + int(h*0.62)), radius=8, fill=c2 + (255,))
        draw.rounded_rectangle((x1 - int(w*0.36), y0 + int(h*0.25), x1 - int(w*0.1), y0 + int(h*0.62)), radius=8, fill=c2 + (255,))
        draw.line([(x0 + int(w*0.2), y1 - int(h*0.18)), (x1 - int(w*0.2), y1 - int(h*0.18))], fill=c3 + (255,), width=stroke)
        return "stylized_cassette"
    if any(k in motif for k in ("crt", "monitor", "screen")):
        draw.rounded_rectangle((x0, y0, x1, y1 - int(h*0.12)), radius=int(h * 0.1), outline=c1 + (255,), width=stroke)
        draw.rectangle((x0 + int(w*0.12), y0 + int(h*0.14), x1 - int(w*0.12), y1 - int(h*0.25)), fill=c2 + (255,))
        draw.rectangle((cx - int(w*0.08), y1 - int(h*0.11), cx + int(w*0.08), y1 - int(h*0.04)), fill=c3 + (255,))
        return "stylized_crt"
    if "loading" in motif or "buffer" in motif:
        draw.rounded_rectangle(box, radius=int(h * 0.2), outline=c1 + (255,), width=stroke)
        sw = int(w * 0.14)
        sx = x0 + int(w * 0.1)
        for i in range(5):
            col = c2 if i < 3 else c4
            draw.rectangle((sx + i * sw, cy - int(h*0.12), sx + i * sw + sw - 6, cy + int(h*0.12)), fill=col + (255,))
        return "stylized_loading"
    if any(k in motif for k in ("cursor", "arrow")):
        draw.polygon([(x0 + int(w*0.2), y0 + int(h*0.08)), (x0 + int(w*0.72), cy), (x0 + int(w*0.42), cy + int(h*0.05)), (x0 + int(w*0.58), y1 - int(h*0.08)), (x0 + int(w*0.42), y1 - int(h*0.03)), (x0 + int(w*0.28), cy + int(h*0.2)), (x0 + int(w*0.2), cy + int(h*0.24))], fill=c1 + (255,))
        return "stylized_cursor"
    if "battery" in motif:
        draw.rounded_rectangle((x0, y0 + int(h*0.08), x1 - stroke*2, y1 - int(h*0.08)), radius=12, outline=c1 + (255,), width=stroke)
        draw.rectangle((x1 - stroke*2, cy - int(h*0.1), x1, cy + int(h*0.1)), fill=c1 + (255,))
        draw.rectangle((x0 + int(w*0.1), y0 + int(h*0.2), x0 + int(w*0.42), y1 - int(h*0.2)), fill=c2 + (255,))
        return "stylized_battery"
    if any(k in motif for k in ("floppy", "disk")):
        draw.rectangle(box, outline=c1 + (255,), width=stroke)
        draw.rectangle((x0 + int(w*0.14), y0 + int(h*0.12), x1 - int(w*0.14), y0 + int(h*0.36)), fill=c2 + (255,))
        draw.rectangle((cx - int(w*0.12), y1 - int(h*0.28), cx + int(w*0.12), y1 - int(h*0.08)), fill=c3 + (255,))
        return "stylized_floppy"
    if any(k in motif for k in ("joystick", "arcade")):
        draw.rounded_rectangle((x0 + int(w*0.08), y0 + int(h*0.5), x1 - int(w*0.08), y1), radius=18, outline=c1 + (255,), width=stroke)
        draw.ellipse((cx - int(w*0.09), y0 + int(h*0.08), cx + int(w*0.09), y0 + int(h*0.28)), fill=c2 + (255,))
        draw.rectangle((cx - int(w*0.02), y0 + int(h*0.26), cx + int(w*0.02), y0 + int(h*0.52)), fill=c2 + (255,))
        return "stylized_joystick"
    draw.ellipse(box, outline=c1 + (255,), width=stroke)
    draw.polygon([(cx, y0 + int(h*0.15)), (x1 - int(w*0.2), y1 - int(h*0.18)), (x0 + int(w*0.2), y1 - int(h*0.18))], fill=c2 + (255,))
    return "generic"


def _draw_text_treatment(draw: ImageDraw.ImageDraw, phrase: str, treatment: str, area: Tuple[int, int, int, int], color: Tuple[int, int, int], rng: random.Random) -> None:
    x0, y0, x1, y1 = area
    cx = (x0 + x1) // 2
    text = (phrase or "").strip().upper()
    if not text:
        return
    compact = text[:28]
    family = "Montserrat-Bold.ttf"
    if treatment in ("chunky_varsity", "bold_single_line_wordmark"):
        size = 82
        font = _load_font(os.path.join("assets", "fonts", "Anton-Regular.ttf"), size)
        while size > 40:
            bb = draw.textbbox((0, 0), compact, font=font)
            if bb[2] - bb[0] <= (x1 - x0):
                break
            size -= 4
            font = _load_font(os.path.join("assets", "fonts", "Anton-Regular.ttf"), size)
        draw.text((cx - (draw.textbbox((0,0), compact, font=font)[2] // 2), y0 + 4), compact, fill=color + (255,), font=font)
        return
    if treatment in ("stacked_slogan", "stacked_two_line", "direct_slogan_lockup") and " " in compact:
        words = compact.split()
        mid = max(1, len(words)//2)
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        font = _load_font(os.path.join("assets", "fonts", family), 56)
        yy = y0 + 6
        for ln in lines:
            bb = draw.textbbox((0,0), ln, font=font)
            draw.text((cx - (bb[2]-bb[0])//2, yy), ln, fill=color + (255,), font=font)
            yy += (bb[3]-bb[1]) + 6
        return
    font = _load_font(os.path.join("assets", "fonts", family), 48)
    bb = draw.textbbox((0,0), compact, font=font)
    draw.text((cx - (bb[2]-bb[0])//2, y0 + max(0, ((y1-y0)-(bb[3]-bb[1]))//2)), compact, fill=color + (255,), font=font)


def _render_vector_hat_art(brief, resolved_style: str) -> Tuple[Image.Image, Dict[str, str]]:
    safe_x0 = (CANVAS_HAT[0] - HAT_SAFE_AREA[0]) // 2
    safe_y0 = (CANVAS_HAT[1] - HAT_SAFE_AREA[1]) // 2
    safe_x1 = safe_x0 + HAT_SAFE_AREA[0]
    safe_y1 = safe_y0 + HAT_SAFE_AREA[1]

    seed = abs(hash(f"{brief.drop}|{brief.motif}|{brief.phrase}|{resolved_style}|{getattr(brief, 'art_direction', '')}"))
    rng = random.Random(seed)
    design_mode = (getattr(brief, "design_mode", "icon_only") or "icon_only").strip().lower()
    type_treatment = (getattr(brief, "type_treatment", "") or getattr(brief, "text_mode", "single_line")).strip().lower()
    layout = (getattr(brief, "layout_archetype", "") or "centered_icon").strip().lower()
    frame_treatment = (getattr(brief, "frame_treatment", "none") or "none").strip().lower()

    best = None
    for _ in range(4):
        canvas = Image.new("RGBA", CANVAS_HAT, (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        c1, c2, c3, c4 = _pick_colors(rng)
        stroke = max(6, int(CANVAS_HAT[0] * 0.0055))

        icon_box = (safe_x0 + 220, safe_y0 + 70, safe_x1 - 220, safe_y1 - 150)
        text_box = (safe_x0 + 80, safe_y1 - 135, safe_x1 - 80, safe_y1)
        if layout == "centered_wordmark":
            icon_box = (safe_x0 + 260, safe_y0 + 80, safe_x1 - 260, safe_y0 + 220)
            text_box = (safe_x0 + 70, safe_y0 + 170, safe_x1 - 70, safe_y1 - 40)
        elif layout == "monogram_lockup":
            icon_box = (safe_x0 + 300, safe_y0 + 70, safe_x1 - 300, safe_y0 + 300)
            text_box = (safe_x0 + 120, safe_y1 - 120, safe_x1 - 120, safe_y1)

        shape_quality = "good"
        icon_present = design_mode != "text_only"
        if icon_present:
            icon_shape = _draw_icon(draw, getattr(brief, "motif", ""), icon_box, (c1, c2, c3, c4), stroke)
            shape_quality = "generic" if icon_shape == "generic" else "refined"

        if design_mode != "icon_only" and getattr(brief, "include_text", False):
            _draw_text_treatment(draw, getattr(brief, "phrase", ""), type_treatment, text_box, c1, rng)

        frame_mode = "none"
        if frame_treatment in ("underline", "ring", "arc", "border"):
            frame_mode = frame_treatment
            if frame_treatment == "underline":
                draw.line([(safe_x0 + 170, safe_y1 - 12), (safe_x1 - 170, safe_y1 - 12)], fill=c3 + (255,), width=stroke)
            elif frame_treatment == "ring" and design_mode != "text_only":
                x0,y0,x1,y1 = icon_box
                draw.ellipse((x0-20,y0-18,x1+20,y1+18), outline=c4 + (255,), width=stroke)
            elif frame_treatment == "arc":
                draw.arc((safe_x0+100, safe_y0+20, safe_x1-100, safe_y1-10), 200, 340, fill=c4 + (255,), width=stroke)
            elif frame_treatment == "border":
                draw.rectangle((safe_x0+60, safe_y0+20, safe_x1-60, safe_y1-20), outline=c4 + (255,), width=stroke)

        safe_fill = ((icon_box[2]-icon_box[0]) if icon_present else (text_box[2]-text_box[0])) / float(HAT_SAFE_AREA[0])
        meta = {
            "composition_mode": f"{design_mode}_{layout}",
            "background_mode": "transparent",
            "frame_mode": frame_mode,
            "safe_area_fill_pct": f"{safe_fill:.3f}",
            "motif_bbox": f"{icon_box[0]},{icon_box[1]},{icon_box[2]},{icon_box[3]}",
            "vector_mode_used": "true",
            "art_direction": getattr(brief, "art_direction", ""),
            "layout_archetype": getattr(brief, "layout_archetype", layout),
            "type_treatment": getattr(brief, "type_treatment", type_treatment),
            "icon_treatment": getattr(brief, "icon_treatment", "clean_silhouette"),
            "frame_treatment": frame_treatment,
            "visual_energy": getattr(brief, "visual_energy", "balanced"),
            "commercial_style_reason": getattr(brief, "commercial_style_reason", ""),
            "plate_dependency": "low",
            "icon_present": "true" if icon_present else "false",
            "shape_quality": shape_quality,
        }
        meta = _score_hat_design(meta, brief)

        if int(meta.get("hierarchy_score", "1")) >= 7 and int(meta.get("visual_balance_score", "1")) >= 7 and meta.get("plate_dependency") == "low":
            return canvas, meta
        best = (canvas, meta)

    if best:
        return best
    return Image.new("RGBA", CANVAS_HAT, (0, 0, 0, 0)), {
        "composition_mode": f"{design_mode}_fallback",
        "background_mode": "transparent",
        "frame_mode": "none",
        "safe_area_fill_pct": "0.720",
        "motif_bbox": "",
        "vector_mode_used": "true",
        "hierarchy_score": "6",
        "visual_balance_score": "6",
        "typography_quality_score": "",
        "icon_quality_score": "",
        "plate_dependency": "low",
    }


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
            include_text = False
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
        else:
            img = make_ai_art(prompt, canvas=CANVAS_HAT)
            meta = {
                "composition_mode": "single_centered_emblem",
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
