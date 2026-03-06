import os, re, json, time, base64
import datetime as dt
from typing import Dict, Any, List, Tuple, Optional

import requests
import pandas as pd
from dotenv import load_dotenv
from rapidfuzz import fuzz
from pytrends.request import TrendReq
import praw
from PIL import Image, ImageDraw, ImageFont, ImageFilter

load_dotenv()

# -----------------------------
# Config
# -----------------------------
OUT_DIR = "out"

PRINTFUL_TOKEN = os.getenv("PRINTFUL_TOKEN")

# GitHub hosting
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_FOLDER = os.getenv("GITHUB_FOLDER", "printfiles").strip("/")

LISTINGS_PER_RUN = int(os.getenv("LISTINGS_PER_RUN", "10"))
GEO = os.getenv("GEO", "US")
NICHE_SEED = [s.strip() for s in os.getenv("NICHE_SEED", "").split(",") if s.strip()]

BASE_PRICE_USD = float(os.getenv("BASE_PRICE_USD", "32.99"))

OFFER_SIZES = [s.strip() for s in os.getenv("OFFER_SIZES", "S,M,L,XL,2XL,3XL").split(",") if s.strip()]
OFFER_COLORS = [s.strip() for s in os.getenv("OFFER_COLORS", "Black,Navy,Maroon,Forest Green,Sport Grey").split(",") if s.strip()]

SUBREDDITS = ["sports", "Parenting", "mommit", "daddit", "funny", "memes", "AskReddit"]

MIN_LEN, MAX_LEN = 6, 48
PRINTABLE_RE = re.compile(r"^[A-Za-z0-9&'’\-\s\.\!\?]+$")

# Safety guardrails
PROFANITY = {"fuck", "shit", "bitch", "asshole", "cunt"}
POLITICS = {"trump", "biden", "maga", "democrat", "republican", "election"}
TRADEMARK_HINTS = ["disney", "marvel", "star wars", "pokemon", "nintendo", "harry potter", "nba", "nfl", "mlb"]

PRINTFUL_API_BASE = "https://api.printful.com"

BLANK_NAME = "Gildan 18000 Crewneck Sweatshirt"
MATERIALS = ["cotton", "polyester"]

# -----------------------------
# Helpers
# -----------------------------
def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

def normalize(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def slugify(s: str) -> str:
    s = normalize(s).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "phrase"

def is_printable(s: str) -> bool:
    return bool(PRINTABLE_RE.match(s))

def flags_for(phrase: str) -> List[str]:
    f = []
    if not is_printable(phrase): f.append("non_printable")
    if not (MIN_LEN <= len(phrase) <= MAX_LEN): f.append("length")
    words = set(re.findall(r"[a-z]+", phrase.lower()))
    if words & PROFANITY: f.append("profanity")
    if words & POLITICS: f.append("politics")
    if any(h in phrase.lower() for h in TRADEMARK_HINTS): f.append("trademark_hint")
    return f

def fuzzy_dedupe(items: List[str], threshold=92) -> List[str]:
    kept = []
    for it in items:
        it = normalize(it)
        if not it:
            continue
        if any(fuzz.token_sort_ratio(it.lower(), k.lower()) >= threshold for k in kept):
            continue
        kept.append(it)
    return kept

def score_phrase(p: str) -> float:
    L = len(p)
    score = 0.0
    if 10 <= L <= 28: score += 10
    elif 29 <= L <= 40: score += 4
    else: score -= 2
    if "!" in p or "?" in p: score += 2
    if len(p.split()) >= 8: score -= 3
    return score

# -----------------------------
# Trend intake
# -----------------------------
def google_trends_terms(seed_terms: List[str]) -> List[str]:
    pytrends = TrendReq(hl="en-US", tz=360)
    terms = []
    try:
        df_trending = pytrends.trending_searches(pn="united_states")
        terms += df_trending[0].dropna().astype(str).tolist()[:30]
    except Exception:
        pass

    for term in seed_terms[:10]:
        try:
            pytrends.build_payload([term], timeframe="now 7-d", geo=GEO)
            rq = pytrends.related_queries()
            top = rq.get(term, {}).get("top")
            rising = rq.get(term, {}).get("rising")
            if top is not None and "query" in top:
                terms += top["query"].dropna().astype(str).tolist()[:10]
            if rising is not None and "query" in rising:
                terms += rising["query"].dropna().astype(str).tolist()[:10]
            time.sleep(1)
        except Exception:
            continue

    return fuzzy_dedupe(terms, 93)[:150]

def reddit_terms() -> List[str]:
    cid = os.getenv("REDDIT_CLIENT_ID")
    csec = os.getenv("REDDIT_CLIENT_SECRET")
    ua = os.getenv("REDDIT_USER_AGENT", "trend_intake/1.0")
    if not cid or not csec:
        return []

    reddit = praw.Reddit(client_id=cid, client_secret=csec, user_agent=ua)
    terms = []
    for sub in SUBREDDITS:
        try:
            for post in reddit.subreddit(sub).hot(limit=60):
                t = normalize(post.title)
                if not t:
                    continue
                if ":" in t:
                    terms.append(normalize(t.split(":", 1)[1]))
                terms.append(t)
        except Exception:
            continue

    terms = [t for t in terms if is_printable(t) and MIN_LEN <= len(t) <= MAX_LEN]
    return fuzzy_dedupe(terms, 92)

def pick_top_phrases() -> List[Tuple[str, float]]:
    seed_terms = NICHE_SEED or ["game day", "sports mom", "practice", "carpool", "coffee"]
    phrases = google_trends_terms(seed_terms) + reddit_terms()
    phrases = fuzzy_dedupe(phrases, 92)

    scored = []
    for p in phrases:
        f = flags_for(p)
        if {"profanity", "politics", "trademark_hint"} & set(f):
            continue
        scored.append((p, score_phrase(p)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:LISTINGS_PER_RUN]

# -----------------------------
# Fonts + simple icon drawing
# -----------------------------
def load_font(size: int) -> ImageFont.ImageFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\ARIALBD.TTF",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def draw_star(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill=(0,0,0,255)):
    # 5-point star polygon
    import math
    pts = []
    for i in range(10):
        ang = math.radians(-90 + i * 36)
        rr = r if i % 2 == 0 else int(r * 0.45)
        pts.append((cx + int(rr * math.cos(ang)), cy + int(rr * math.sin(ang))))
    draw.polygon(pts, fill=fill)

def draw_lightning(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, fill=(0,0,0,255)):
    pts = [
        (x + int(w*0.55), y),
        (x + int(w*0.20), y + int(h*0.55)),
        (x + int(w*0.48), y + int(h*0.55)),
        (x + int(w*0.15), y + h),
        (x + int(w*0.85), y + int(h*0.40)),
        (x + int(w*0.55), y + int(h*0.40)),
    ]
    draw.polygon(pts, fill=fill)

def add_distress(img: Image.Image, amount: int = 14) -> Image.Image:
    # Light “distress” speckle: subtract random noise alpha
    import random
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    for _ in range((w*h)//(amount*amount)):
        x = random.randint(0, w-1)
        y = random.randint(0, h-1)
        r,g,b,a = px[x,y]
        if a > 0 and random.random() < 0.6:
            px[x,y] = (r,g,b,int(a*0.2))
    return img

# -----------------------------
# Better design generation (3 styles)
# -----------------------------
def make_design_variants(phrase: str, folder: str) -> str:
    """
    Generates 3 design variants. Returns the chosen design path.
    """
    W, H = 4500, 5400
    phrase_up = phrase.upper()

    def render_variant(style: int) -> Image.Image:
        img = Image.new("RGBA", (W, H), (0,0,0,0))
        d = ImageDraw.Draw(img)

        if style == 1:
            # Badge style
            d.rounded_rectangle([650, 900, W-650, H-900], radius=160, outline=(0,0,0,255), width=28)
            draw_star(d, 900, 1150, 90)
            draw_star(d, W-900, 1150, 90)
            font = load_font(240)
            lines = wrap_text(d, phrase_up, font, max_width=3000)
            y = 1800
            for line in lines[:4]:
                tw = d.textlength(line, font=font)
                x = (W - tw)//2
                d.text((x, y), line, font=font, fill=(0,0,0,255))
                y += 330

        elif style == 2:
            # Big headline + lightning corners
            draw_lightning(d, 700, 900, 550, 1100)
            draw_lightning(d, W-1250, 900, 550, 1100)
            font = load_font(320)
            lines = wrap_text(d, phrase_up, font, max_width=3300)
            y = 1700
            for line in lines[:3]:
                tw = d.textlength(line, font=font)
                x = (W - tw)//2
                d.text((x, y), line, font=font, fill=(0,0,0,255))
                y += 420
            # small subtext
            sub = "GAME DAY ENERGY" if "game" in phrase.lower() else "CREWNECK VIBES"
            f2 = load_font(150)
            tw = d.textlength(sub, font=f2)
            d.text(((W-tw)//2, y+150), sub, font=f2, fill=(0,0,0,255))

        else:
            # Stacked with divider lines + stars
            font = load_font(260)
            lines = wrap_text(d, phrase_up, font, max_width=3400)
            y = 1650
            d.line([900, 1450, W-900, 1450], fill=(0,0,0,255), width=18)
            for line in lines[:4]:
                tw = d.textlength(line, font=font)
                d.text(((W-tw)//2, y), line, font=font, fill=(0,0,0,255))
                y += 360
            d.line([900, y+60, W-900, y+60], fill=(0,0,0,255), width=18)
            draw_star(d, W//2, y+240, 120)

        return add_distress(img, amount=16)

    paths = []
    for style in (1,2,3):
        img = render_variant(style)
        p = os.path.join(folder, f"design_print_style{style}.png")
        img.save(p, "PNG")
        paths.append(p)

    # Choose best = the one with most non-transparent pixels (rough proxy for “not too empty”)
    best_path = paths[0]
    best_score = -1
    for p in paths:
        im = Image.open(p).convert("RGBA")
        alpha = im.split()[-1]
        nonzero = sum(1 for v in alpha.getdata() if v > 10)
        if nonzero > best_score:
            best_score = nonzero
            best_path = p

    # Copy chosen to canonical name
    chosen = Image.open(best_path).convert("RGBA")
    final_path = os.path.join(folder, "design_print.png")
    chosen.save(final_path, "PNG")
    return final_path

def make_mockups(phrase: str, folder: str) -> Dict[str, str]:
    # Same as before, decent enough for Etsy listing images
    img = Image.new("RGB", (2000, 2000), "white")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([350, 350, 1650, 1750], radius=90, outline="black", width=10)
    d.rounded_rectangle([520, 520, 1480, 1600], radius=60, outline="black", width=6)

    font = load_font(120)
    lines = wrap_text(d, phrase.upper(), font, max_width=850)
    y = 800 - (len(lines) * 80)
    for line in lines[:5]:
        w = d.textlength(line, font=font)
        d.text(((2000 - w) / 2, y), line, fill="black", font=font)
        y += 150
    p1 = os.path.join(folder, "mockup_01.png")
    img.save(p1, "PNG")

    img2 = Image.new("RGB", (2000, 2000), "white")
    d2 = ImageDraw.Draw(img2)
    font2 = load_font(180)
    lines2 = wrap_text(d2, phrase, font2, max_width=1500)
    y = 900 - (len(lines2) * 100)
    for line in lines2[:4]:
        w = d2.textlength(line, font=font2)
        d2.text(((2000 - w) / 2, y), line, fill="black", font=font2)
        y += 220
    p2 = os.path.join(folder, "mockup_02.png")
    img2.save(p2, "PNG")

    img3 = Image.new("RGB", (2000, 2000), "white")
    d3 = ImageDraw.Draw(img3)
    d3.text((80, 80), f"SIZE CHART ({BLANK_NAME})", fill="black", font=load_font(80))
    d3.rectangle([80, 220, 1920, 1700], outline="black", width=6)
    headers = ["Size", "Chest (in)", "Length (in)"]
    rows = [
        ["S", "34-36", "27"],
        ["M", "38-40", "28"],
        ["L", "42-44", "29"],
        ["XL", "46-48", "30"],
        ["2XL", "50-52", "31"],
        ["3XL", "54-56", "32"],
    ]
    x0, y0 = 120, 320
    colw = [400, 600, 600]
    d3.text((x0, y0), headers[0], fill="black", font=load_font(64))
    d3.text((x0 + colw[0], y0), headers[1], fill="black", font=load_font(64))
    d3.text((x0 + colw[0] + colw[1], y0), headers[2], fill="black", font=load_font(64))
    y = y0 + 110
    font_row = load_font(58)
    for r in rows:
        d3.text((x0, y), r[0], fill="black", font=font_row)
        d3.text((x0 + colw[0], y), r[1], fill="black", font=font_row)
        d3.text((x0 + colw[0] + colw[1], y), r[2], fill="black", font=font_row)
        y += 95
    p3 = os.path.join(folder, "size_chart.png")
    img3.save(p3, "PNG")

    return {"mockup_01": p1, "mockup_02": p2, "size_chart": p3}

# -----------------------------
# Listing pack
# -----------------------------
def build_listing_pack(phrase: str) -> Dict[str, Any]:
    title = f"{phrase} Crewneck Sweatshirt, {BLANK_NAME}, Unisex Cozy Pullover, Gift Idea"
    title = title[:140]
    tags = [
        phrase.lower()[:20],
        "crewneck", "sweatshirt", "unisex", "cozy",
        "gift idea", "sports mom", "game day", "practice life",
        "carpool", "coffee lover", "weekend vibes", "heavy blend",
    ]
    tags = [t[:20] for t in tags][:13]
    desc = f"""{phrase}

COZY UNISEX CREWNECK ({BLANK_NAME})
• Soft, warm, classic fit
• Printed to order

VARIATIONS
Sizes: {", ".join(OFFER_SIZES)}
Colors: {", ".join(OFFER_COLORS)}

SIZING
See size chart in listing photos.

PRODUCTION & SHIPPING
Made to order. Tracking provided when shipped.
"""
    return {
        "phrase": phrase,
        "title": title,
        "description": desc,
        "tags": tags,
        "materials": MATERIALS,
        "price_usd": round(BASE_PRICE_USD, 2),
        "sizes": OFFER_SIZES,
        "colors": OFFER_COLORS,
        "blank": BLANK_NAME,
    }

# -----------------------------
# GitHub upload (commit file via Contents API)
# -----------------------------
def gh_headers():
    return {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}

def gh_put_file(repo_path: str, local_path: str, commit_message: str) -> str:
    """
    Creates/updates a file in the GitHub repo using the Contents API.
    Returns the raw.githubusercontent.com URL.
    """
    if not (GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO):
        raise RuntimeError("Missing GitHub settings in .env (GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO).")

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{repo_path}"
    # get existing sha if exists
    sha = None
    r0 = requests.get(url, headers=gh_headers(), params={"ref": GITHUB_BRANCH}, timeout=30)
    if r0.status_code == 200:
        sha = r0.json().get("sha")

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "message": commit_message,
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=gh_headers(), json=payload, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub upload failed {r.status_code}: {r.text}")

    # Raw URL format :contentReference[oaicite:3]{index=3}
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_BRANCH}/{repo_path}"
    return raw_url

# -----------------------------
# Printful: add file by URL
# -----------------------------
def pf_headers():
    return {"Authorization": f"Bearer {PRINTFUL_TOKEN}", "Content-Type": "application/json"}

def printful_add_file_by_url(file_url: str) -> Optional[int]:
    """
    Printful files endpoint: add file by providing URL. :contentReference[oaicite:4]{index=4}
    """
    if not PRINTFUL_TOKEN:
        return None
    url = f"{PRINTFUL_API_BASE}/files"
    r = requests.post(url, headers=pf_headers(), json={"url": file_url}, timeout=60)
    if r.status_code >= 300:
        print(f"Printful add-file-by-url failed: {r.status_code} {r.text}")
        return None
    j = r.json()
    return (j.get("result") or {}).get("id")

# -----------------------------
# Runner
# -----------------------------
def run():
    ensure_dir(OUT_DIR)
    stamp = dt.date.today().isoformat()
    run_dir = os.path.join(OUT_DIR, stamp)
    ensure_dir(run_dir)

    top = pick_top_phrases()
    pd.DataFrame(top, columns=["phrase", "score"]).to_csv(os.path.join(run_dir, "top10.csv"), index=False)

    listings_rows = []

    for idx, (phrase, score) in enumerate(top, start=1):
        phrase = normalize(phrase)
        s = slugify(phrase)
        folder = os.path.join(run_dir, f"{idx:02d}_{s}")
        ensure_dir(folder)

        pack = build_listing_pack(phrase)

        # Write text assets
        for name, content in [
            ("etsy_title.txt", pack["title"]),
            ("etsy_description.txt", pack["description"]),
            ("etsy_tags.txt", ", ".join(pack["tags"])),
        ]:
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write(content)

        # Create improved design + images
        design_path = make_design_variants(phrase, folder)
        mockups = make_mockups(phrase, folder)

        # Upload design_print.png to GitHub, then register in Printful by URL
        printful_file_id = None
        design_raw_url = None
        if GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO:
            repo_path = f"{GITHUB_FOLDER}/{stamp}/{idx:02d}_{s}/design_print.png"
            design_raw_url = gh_put_file(repo_path, design_path, f"Add printfile: {stamp} {idx:02d} {phrase}")
            printful_file_id = printful_add_file_by_url(design_raw_url)

        pack["design_print_path"] = design_path
        pack["design_raw_url"] = design_raw_url
        pack["mockups"] = mockups
        pack["printful_file_id"] = printful_file_id

        with open(os.path.join(folder, "listing.json"), "w", encoding="utf-8") as f:
            json.dump(pack, f, ensure_ascii=False, indent=2)

        listings_rows.append({
            "folder": folder,
            "phrase": phrase,
            "score": score,
            "title": pack["title"],
            "price_usd": pack["price_usd"],
            "tags": "|".join(pack["tags"]),
            "sizes": "|".join(pack["sizes"]),
            "colors": "|".join(pack["colors"]),
            "design_print_path": design_path,
            "design_raw_url": design_raw_url or "",
            "printful_file_id": printful_file_id if printful_file_id is not None else "",
            "mockup_01": mockups["mockup_01"],
            "mockup_02": mockups["mockup_02"],
            "size_chart": mockups["size_chart"],
        })

        print(f"[{idx}/{len(top)}] Built pack: {phrase} | GitHub raw: {bool(design_raw_url)} | Printful file id: {printful_file_id}")

    pd.DataFrame(listings_rows).to_csv(os.path.join(run_dir, "listings.csv"), index=False)
    print(f"\nDone. Output folder:\n{run_dir}\n")

if __name__ == "__main__":
    run()