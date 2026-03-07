import os
from PIL import Image, ImageOps


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


def score_png(img: Image.Image) -> dict:
    img = img.convert("RGBA")
    w, h = img.size
    a = img.getchannel("A")
    nonzero = sum(1 for p in a.getdata() if p > 10)
    coverage = nonzero / float(max(1, w * h))

    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img.convert("RGB"), mask=a)
    gray = ImageOps.grayscale(rgb)
    mn, mx = gray.getextrema()
    contrast = (mx - mn) / 255.0

    # color count on non-transparent pixels
    colors = rgb.getcolors(maxcolors=1_000_000) or []
    color_count = len(colors)

    # center-weight check: % of filled pixels in center 60% region
    cx0, cy0 = int(w * 0.2), int(h * 0.2)
    cx1, cy1 = int(w * 0.8), int(h * 0.8)
    center_alpha = a.crop((cx0, cy0, cx1, cy1))
    center_nonzero = sum(1 for p in center_alpha.getdata() if p > 10)
    center_coverage = center_nonzero / float(max(1, nonzero))

    # gradient-like estimate: too many near-neighbor tonal deltas
    pix = list(gray.getdata())
    diffs = 0
    checks = 0
    for y in range(0, h - 1, max(1, h // 64)):
        for x in range(0, w - 1, max(1, w // 64)):
            i = y * w + x
            d1 = abs(pix[i] - pix[i + 1])
            d2 = abs(pix[i] - pix[i + w])
            for d in (d1, d2):
                checks += 1
                if 4 <= d <= 24:
                    diffs += 1
    gradient_ratio = diffs / float(max(1, checks))

    # detail estimate: edge density
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_vals = list(edges.getdata())
    detail_ratio = sum(1 for p in edge_vals if p > 40) / float(max(1, w * h))

    return {
        "coverage": coverage,
        "contrast": contrast,
        "color_count": color_count,
        "center_coverage": center_coverage,
        "gradient_ratio": gradient_ratio,
        "detail_ratio": detail_ratio,
    }


# Local import to keep module load cheap
from PIL import ImageFilter


def pass_fail(img: Image.Image) -> tuple[bool, str, dict]:
    s = score_png(img)
    cov = s["coverage"]
    con = s["contrast"]
    if cov < QG_MIN_COVERAGE:
        return False, "too_empty", s
    if cov > QG_MAX_COVERAGE:
        return False, "too_full", s
    if con < QG_MIN_CONTRAST:
        return False, "low_contrast", s
    if s["color_count"] > QG_MAX_COLORS + 2:  # small tolerance for anti-aliasing
        return False, "too_many_colors", s
    if s["center_coverage"] < QG_MIN_CENTER_COVERAGE:
        return False, "off_center_composition", s
    if s["gradient_ratio"] > QG_GRADIENT_RATIO_MAX:
        return False, "gradient_like_rendering", s
    if s["detail_ratio"] > QG_DETAIL_RATIO_MAX:
        return False, "over_detailed", s
    return True, "", s
