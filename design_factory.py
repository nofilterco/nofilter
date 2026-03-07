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


def _render_vector_hat_art(brief, resolved_style: str) -> Tuple[Image.Image, Dict[str, str]]:
    canvas = Image.new("RGBA", CANVAS_HAT, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    safe_x0 = (CANVAS_HAT[0] - HAT_SAFE_AREA[0]) // 2
    safe_y0 = (CANVAS_HAT[1] - HAT_SAFE_AREA[1]) // 2
    safe_x1 = safe_x0 + HAT_SAFE_AREA[0]
    safe_y1 = safe_y0 + HAT_SAFE_AREA[1]

    seed = abs(hash(f"{brief.drop}|{brief.motif}|{brief.phrase}|{resolved_style}"))
    rng = random.Random(seed)

    fill_pct = rng.uniform(0.72, 0.84)
    motif_w = int(HAT_SAFE_AREA[0] * fill_pct)
    motif_h = int(HAT_SAFE_AREA[1] * rng.uniform(0.6, 0.82))
    cx = (safe_x0 + safe_x1) // 2
    cy = (safe_y0 + safe_y1) // 2
    bbox = (cx - motif_w // 2, cy - motif_h // 2, cx + motif_w // 2, cy + motif_h // 2)

    palette = [_hex_to_rgb(c) for c in EMBROIDERY_CONFIG.allowed_thread_palette]
    chosen = rng.sample(palette, k=min(5, len(palette)))
    bg, primary, accent, accent2, accent3 = (chosen + chosen[:5])[:5]
    stroke = max(6, int(CANVAS_HAT[0] * 0.005))

    shape_mode = resolved_style
    design_mode = (getattr(brief, "design_mode", "icon_only") or "icon_only").strip().lower()
    text_mode = (getattr(brief, "text_mode", "") or "").strip().lower()
    if shape_mode in ("text-lockup", "wordmark-icon") and brief.phrase:
        shape_mode = "direct-front-graphic"

    x0, y0, x1, y1 = bbox
    motif = (getattr(brief, "motif", "") or "").lower()
    if "cassette" in motif or "tape" in motif:
        draw.rounded_rectangle(bbox, radius=int(motif_h * 0.12), fill=primary + (255,), outline=accent + (255,), width=stroke)
        win_w, win_h = int(motif_w * 0.22), int(motif_h * 0.28)
        draw.rounded_rectangle((cx - win_w - 10, cy - win_h // 2, cx - 10, cy + win_h // 2), radius=8, fill=accent2 + (255,))
        draw.rounded_rectangle((cx + 10, cy - win_h // 2, cx + win_w + 10, cy + win_h // 2), radius=8, fill=accent2 + (255,))
        draw.rectangle((cx - motif_w // 8, cy + motif_h // 6, cx + motif_w // 8, cy + motif_h // 6 + stroke * 2), fill=accent3 + (255,))
    elif "crt" in motif or "monitor" in motif or "screen" in motif:
        draw.rounded_rectangle(bbox, radius=int(motif_h * 0.1), fill=primary + (255,), outline=accent + (255,), width=stroke)
        inset = int(motif_w * 0.12)
        draw.rectangle((x0 + inset, y0 + inset, x1 - inset, y1 - inset - stroke * 3), fill=accent2 + (255,))
        draw.rectangle((cx - motif_w // 10, y1 - inset - stroke * 2, cx + motif_w // 10, y1 - inset), fill=accent3 + (255,))
    elif "battery" in motif:
        draw.rounded_rectangle(bbox, radius=int(motif_h * 0.12), fill=primary + (255,), outline=accent + (255,), width=stroke)
        draw.rectangle((x1, cy - motif_h // 8, x1 + stroke * 2, cy + motif_h // 8), fill=accent + (255,))
        draw.rectangle((x0 + stroke * 2, y0 + stroke * 2, x0 + motif_w // 3, y1 - stroke * 2), fill=accent2 + (255,))
    elif "loading" in motif or "buffer" in motif:
        draw.rounded_rectangle(bbox, radius=int(motif_h * 0.2), fill=primary + (255,), outline=accent + (255,), width=stroke)
        seg_w = int((motif_w * 0.72) / 5)
        sx = cx - int(motif_w * 0.36)
        for i in range(5):
            col = accent2 if i < 3 else bg
            draw.rectangle((sx + i * seg_w, cy - motif_h // 8, sx + i * seg_w + seg_w - 5, cy + motif_h // 8), fill=col + (255,))
    elif shape_mode in ("centered-emblem", "direct-front-graphic", "bold-icon-block"):
        draw.ellipse(bbox, fill=primary + (255,), outline=accent + (255,), width=stroke)
        in_pad = int(motif_w * 0.22)
        draw.polygon([(cx, y0 + in_pad), (x1 - in_pad, y1 - in_pad), (x0 + in_pad, y1 - in_pad)], fill=accent2 + (255,))
    elif shape_mode in ("geometric-monogram", "monoline-symbol"):
        draw.rounded_rectangle(bbox, radius=int(motif_h * 0.18), fill=primary + (255,), outline=accent + (255,), width=stroke)
        draw.line([(x0 + motif_w * 0.25, y0 + motif_h * 0.25), (cx, y1 - motif_h * 0.2), (x1 - motif_w * 0.25, y0 + motif_h * 0.25)], fill=accent2 + (255,), width=stroke)
    elif shape_mode == "simplified-mascot-icon":
        head = (cx - motif_w // 4, y0 + motif_h // 6, cx + motif_w // 4, cy + motif_h // 8)
        body = (cx - motif_w // 3, cy - motif_h // 16, cx + motif_w // 3, y1 - motif_h // 8)
        draw.ellipse(head, fill=primary + (255,), outline=accent + (255,), width=stroke)
        draw.rounded_rectangle(body, radius=int(motif_h * 0.1), fill=accent2 + (255,), outline=accent + (255,), width=stroke)
        draw.rectangle((cx - stroke, cy - stroke, cx + stroke, y1 - motif_h // 5), fill=accent3 + (255,))
    else:
        draw.polygon([(cx, y0), (x1, cy), (cx, y1), (x0, cy)], fill=primary + (255,), outline=accent + (255,), width=stroke)
        draw.ellipse((cx - motif_w // 5, cy - motif_h // 5, cx + motif_w // 5, cy + motif_h // 5), fill=accent2 + (255,))

    # optional motif-specific frame only
    frame_mode = "none"
    if (brief.motif_frame or "").lower() in ("circle", "shield", "hex") and rng.random() < 0.25:
        frame_mode = "motif_specific"
        pad = stroke * 2
        draw.rounded_rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), radius=int(motif_h * 0.2), outline=accent3 + (255,), width=stroke)

    if brief.include_text and brief.phrase and len(brief.phrase) <= 22:
        font = _load_font(os.path.join("assets", "fonts", "Montserrat-Bold.ttf"), max(36, int(motif_h * 0.12)))
        text = brief.phrase.upper()
        if design_mode in ("text_only", "short_quote", "meme_phrase", "nostalgia_wordmark"):
            if text_mode == "stacked_two_line" and " " in text:
                words = text.split()
                mid = max(1, len(words) // 2)
                lines = [" ".join(words[:mid]), " ".join(words[mid:])]
                h = 0
                bbs = []
                for ln in lines:
                    b = draw.textbbox((0, 0), ln, font=font)
                    bbs.append(b)
                    h += (b[3] - b[1]) + 10
                y = cy - h // 2
                for i, ln in enumerate(lines):
                    b = bbs[i]
                    tx = cx - (b[2] - b[0]) // 2
                    draw.text((tx, y), ln, font=font, fill=accent + (255,))
                    y += (b[3] - b[1]) + 10
            else:
                tb = draw.textbbox((0, 0), text, font=font)
                tx = cx - (tb[2] - tb[0]) // 2
                ty = cy - (tb[3] - tb[1]) // 2
                draw.text((tx, ty), text, font=font, fill=accent + (255,))
        else:
            tb = draw.textbbox((0, 0), text, font=font)
            tw = tb[2] - tb[0]
            tx = cx - tw // 2
            ty = min(safe_y1 - (tb[3] - tb[1]) - 4, y1 + 8)
            draw.text((tx, ty), text, font=font, fill=accent + (255,))

    safe_fill = motif_w / float(HAT_SAFE_AREA[0])
    meta = {
        "composition_mode": f"{design_mode}_centered",
        "background_mode": "transparent",
        "frame_mode": frame_mode,
        "safe_area_fill_pct": f"{safe_fill:.3f}",
        "motif_bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "vector_mode_used": "true",
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
