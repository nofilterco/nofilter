import os
from typing import Tuple, Union
from PIL import Image, ImageFilter, ImageOps


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


QG_MIN_COVERAGE = _env_float("QG_MIN_COVERAGE", 0.12)
QG_MAX_COVERAGE = _env_float("QG_MAX_COVERAGE", 0.72)
QG_MIN_CONTRAST = _env_float("QG_MIN_CONTRAST", 0.09)
QG_MIN_CENTER_COVERAGE = _env_float("QG_MIN_CENTER_COVERAGE", 0.55)
QG_MAX_COLORS = int(_env_float("QG_MAX_COLORS", 6))
QG_GRADIENT_RATIO_MAX = _env_float("QG_GRADIENT_RATIO_MAX", 0.20)
QG_DETAIL_RATIO_MAX = _env_float("QG_DETAIL_RATIO_MAX", 0.18)
QG_MAX_EDGE_NOISE = _env_float("QG_MAX_EDGE_NOISE", 0.24)
QG_MIN_SILHOUETTE_FILL = _env_float("QG_MIN_SILHOUETTE_FILL", 0.38)


def _load_input(src: Union[Image.Image, str]) -> Image.Image:
    if isinstance(src, Image.Image):
        return src.convert("RGBA")
    return Image.open(src).convert("RGBA")


def _safe_bbox(alpha: Image.Image) -> Tuple[int, int, int, int]:
    bbox = alpha.getbbox()
    return bbox if bbox else (0, 0, alpha.width, alpha.height)


def score_png(src: Union[Image.Image, str]) -> dict:
    img = _load_input(src)
    w, h = img.size
    a = img.getchannel("A")
    nonzero = sum(1 for p in a.getdata() if p > 10)
    coverage = nonzero / float(max(1, w * h))

    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img.convert("RGB"), mask=a)
    gray = ImageOps.grayscale(rgb)
    mn, mx = gray.getextrema()
    contrast = (mx - mn) / 255.0

    colors = rgb.getcolors(maxcolors=1_000_000) or []
    color_count = len(colors)

    cx0, cy0 = int(w * 0.2), int(h * 0.2)
    cx1, cy1 = int(w * 0.8), int(h * 0.8)
    center_nonzero = sum(1 for p in a.crop((cx0, cy0, cx1, cy1)).getdata() if p > 10)
    center_coverage = center_nonzero / float(max(1, nonzero))

    pix = list(gray.getdata())
    diffs = 0
    checks = 0
    for y in range(0, h - 1, max(1, h // 64)):
        for x in range(0, w - 1, max(1, w // 64)):
            i = y * w + x
            for d in (abs(pix[i] - pix[i + 1]), abs(pix[i] - pix[i + w])):
                checks += 1
                if 4 <= d <= 24:
                    diffs += 1
    gradient_ratio = diffs / float(max(1, checks))

    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_vals = list(edges.getdata())
    detail_ratio = sum(1 for p in edge_vals if p > 40) / float(max(1, w * h))

    bbox = _safe_bbox(a)
    bw, bh = max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])
    bbox_area = bw * bh
    silhouette_fill_ratio = nonzero / float(max(1, bbox_area))
    edge_noise_ratio = sum(1 for p in edge_vals if 20 < p < 60) / float(max(1, w * h))

    top_strip = a.crop((0, 0, w, max(1, int(h * 0.08))))
    bottom_strip = a.crop((0, int(h * 0.92), w, h))
    has_background_block = (sum(1 for p in top_strip.getdata() if p > 10) > (top_strip.width * top_strip.height * 0.7)) or (
        sum(1 for p in bottom_strip.getdata() if p > 10) > (bottom_strip.width * bottom_strip.height * 0.7)
    )

    border_band = []
    for x in range(w):
        border_band.append(a.getpixel((x, 0)))
        border_band.append(a.getpixel((x, h - 1)))
    for y in range(h):
        border_band.append(a.getpixel((0, y)))
        border_band.append(a.getpixel((w - 1, y)))
    has_patch_border = sum(1 for p in border_band if p > 10) / float(max(1, len(border_band))) > 0.65

    # quick scatter detection: occupied cells in 3x3 grid
    occupied = 0
    for gy in range(3):
        for gx in range(3):
            sx0, sy0 = int(w * gx / 3), int(h * gy / 3)
            sx1, sy1 = int(w * (gx + 1) / 3), int(h * (gy + 1) / 3)
            cell = a.crop((sx0, sy0, sx1, sy1))
            cell_fill = sum(1 for p in cell.getdata() if p > 10)
            if cell_fill > (cell.width * cell.height * 0.06):
                occupied += 1
    sticker_layout_score = occupied

    palette_used = sorted({"#%02x%02x%02x" % c[1] for c in colors})[:QG_MAX_COLORS]

    return {
        "coverage": coverage,
        "contrast": contrast,
        "raw_color_count": color_count,
        "final_color_count": color_count,
        "color_count": color_count,
        "center_coverage": center_coverage,
        "gradient_ratio": gradient_ratio,
        "detail_ratio": detail_ratio,
        "edge_noise_ratio": edge_noise_ratio,
        "silhouette_fill_ratio": silhouette_fill_ratio,
        "has_background_block": bool(has_background_block),
        "has_patch_border": bool(has_patch_border),
        "sticker_layout_score": sticker_layout_score,
        "palette_used": palette_used,
        "motif_bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
    }


def pass_fail(src: Union[Image.Image, str]) -> tuple[bool, str, dict]:
    s = score_png(src)
    s["auto_quantized"] = False

    if s["coverage"] < QG_MIN_COVERAGE:
        return False, "too_empty", s
    if s["coverage"] > QG_MAX_COVERAGE:
        return False, "too_full", s
    if s["contrast"] < QG_MIN_CONTRAST:
        return False, "low_contrast", s
    if s["final_color_count"] > QG_MAX_COLORS:
        return False, "too_many_colors", s
    if s["center_coverage"] < QG_MIN_CENTER_COVERAGE:
        return False, "off_center_composition", s
    if s["gradient_ratio"] > QG_GRADIENT_RATIO_MAX:
        return False, "gradient_like_rendering", s
    if s["detail_ratio"] > QG_DETAIL_RATIO_MAX:
        return False, "over_detailed", s
    if s["edge_noise_ratio"] > QG_MAX_EDGE_NOISE:
        return False, "edge_noise_too_high", s
    if s["silhouette_fill_ratio"] < QG_MIN_SILHOUETTE_FILL:
        return False, "weak_silhouette", s
    if s["has_background_block"]:
        return False, "background_block_detected", s
    if s["has_patch_border"]:
        return False, "patch_border_detected", s
    if s["sticker_layout_score"] >= 7:
        return False, "sticker_layout_detected", s
    return True, "", s
