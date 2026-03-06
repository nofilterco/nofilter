import os
import random
import textwrap
from typing import List, Tuple, Optional, Union

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

from openai_image import generate_image_pil
from nostalgia_blueprint import (
    pick_brief,
    build_hat_prompt,
    detect_risk,
    MAX_THREAD_COLORS,
    STYLE_DIRECTIVES,
)

CANVAS_TEE = (4500, 5400)
CANVAS_HAT = (3000, 3000)


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


def _center_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    box: Tuple[int, int, int, int],
    line_spacing: float = 1.05,
) -> None:
    x0, y0, x1, y1 = box

    lines = _wrap_lines(text, width=18)
    widths: List[int] = []
    heights: List[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        widths.append(bbox[2] - bbox[0])
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


def quantize_rgba(img: Image.Image, colors: int = MAX_THREAD_COLORS) -> Image.Image:
    img = img.convert("RGBA")
    alpha = img.getchannel("A")

    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img.convert("RGB"), mask=alpha)

    rgb = ImageOps.autocontrast(rgb, cutoff=1)
    rgb = rgb.filter(ImageFilter.MedianFilter(size=3))

    pal = rgb.convert(
        "P",
        palette=Image.Palette.ADAPTIVE,
        colors=max(2, int(colors)),
        dither=Image.Dither.NONE,
    )
    rgb2 = pal.convert("RGB")

    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(rgb2, mask=alpha)

    if os.getenv("EMBROIDERY_SNAP", "1").strip().lower() in ("1", "true", "yes", "y", "on"):
        w, h = out.size
        scale = float(os.getenv("EMBROIDERY_SNAP_SCALE", "0.6"))
        try:
            nw, nh = max(256, int(w * scale)), max(256, int(h * scale))
            out = out.resize((nw, nh), resample=Image.Resampling.NEAREST).resize((w, h), resample=Image.Resampling.NEAREST)
        except Exception:
            pass

    return out


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
        w = bbox[2] - bbox[0]
        if w <= (box[2] - box[0]):
            break
        size -= 20

    font = _load_font(font_path, size)
    _center_text(draw, phrase, font, box)
    return img


def make_ai_art(prompt: str, *, canvas: Tuple[int, int]) -> Image.Image:
    base = Image.new("RGBA", canvas, (0, 0, 0, 0))
    art = generate_image_pil(prompt).convert("RGBA")

    art = ImageOps.contain(art, (int(canvas[0] * 0.86), int(canvas[1] * 0.86)))
    x = (canvas[0] - art.size[0]) // 2
    y = (canvas[1] - art.size[1]) // 2
    base.paste(art, (x, y), mask=art.getchannel("A"))
    return base


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
    return_prompt: bool = False,
) -> Union[Image.Image, Tuple[Image.Image, str]]:
    style_in = (style or "ai_art").strip().lower()
    product_type = (product_type or "hat").strip().lower()

    for t in (title, phrase, niche):
        risk = detect_risk(t or "")
        if risk:
            raise ValueError(f"Blocked by safety gate: {risk}")

    if product_type == "hat":
        generate_mode = (os.getenv("GENERATE_MODE") or "raster").strip().lower()
        if generate_mode not in ("raster", "png"):
            # SVG-first path is intentionally gated until fully wired.
            generate_mode = "raster"

        if include_text is None:
            include_text = False

        brief = pick_brief(drop=drop, include_text=bool(include_text))

        # Deterministic context (Option B) overrides brief fields
        if brief_context and isinstance(brief_context, dict):
            for k, v in brief_context.items():
                if hasattr(brief, k) and v not in (None, ""):
                    setattr(brief, k, str(v))

        # phrase handling for include_text
        if include_text:
            if phrase:
                brief.phrase = phrase
            else:
                if not getattr(brief, "phrase", ""):
                    brief.phrase = "NO FILTER"
        else:
            brief.phrase = ""

        # resolve style key (archetype)
        style_key = style_in if style_in not in ("ai_art", "", None) else ""
        if style_key and style_key in STYLE_DIRECTIVES:
            resolved_style = style_key
        else:
            resolved_style = getattr(brief, "style", "icon-minimal")
            if resolved_style not in STYLE_DIRECTIVES:
                resolved_style = "icon-minimal"

        brief.style = resolved_style

        prompt = build_hat_prompt(brief)
        img = make_ai_art(prompt, canvas=CANVAS_HAT)
        img = quantize_rgba(img, colors=MAX_THREAD_COLORS)

        if return_prompt:
            return img, prompt
        return img

    # legacy tee path
    fonts = [
        os.path.join("assets", "fonts", "Anton-Regular.ttf"),
        os.path.join("assets", "fonts", "Montserrat-Bold.ttf"),
    ]
    font_path = random.choice(fonts)

    if style_in == "mix":
        style_in = random.choices(["text", "ai_art"], weights=[25, 75])[0]

    if style_in == "text":
        return make_text_only(phrase, font_path)

    prompt = (
        f"Professional high-detail t-shirt graphic inspired by {niche}. "
        "Single large central subject, bold silhouette, strong contrast, clean edges, "
        "vector/screenprint style, transparent background, no text, no watermark."
    )
    img = make_ai_art(prompt, canvas=CANVAS_TEE)
    if return_prompt:
        return img, prompt
    return img
