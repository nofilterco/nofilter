import os
from PIL import Image, ImageOps

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

QG_MIN_COVERAGE = _env_float("QG_MIN_COVERAGE", 0.18)
QG_MAX_COVERAGE = _env_float("QG_MAX_COVERAGE", 0.75)
QG_MIN_CONTRAST = _env_float("QG_MIN_CONTRAST", 0.07)

def score_png(img: Image.Image) -> dict:
    img = img.convert("RGBA")
    w, h = img.size
    a = img.getchannel("A")
    alpha_pixels = a.getdata()
    nonzero = sum(1 for p in alpha_pixels if p > 10)
    coverage = nonzero / float(w * h)

    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img.convert("RGB"), mask=a)
    gray = ImageOps.grayscale(rgb)
    mn, mx = gray.getextrema()
    contrast = (mx - mn) / 255.0

    return {"coverage": coverage, "contrast": contrast}

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
    return True, "", s
