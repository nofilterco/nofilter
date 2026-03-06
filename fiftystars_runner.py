import os, re, json, time, base64, hashlib, secrets
import datetime as dt
from urllib.parse import urlencode
from typing import Dict, Any, List, Tuple, Optional

import requests
import pandas as pd
from dotenv import load_dotenv
from rapidfuzz import fuzz
from pytrends.request import TrendReq
import praw

from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request

load_dotenv()

# -----------------------------
# Config
# -----------------------------
OUT_DIR = "out"
STATE_DIR = "state"
TOKENS_PATH = os.path.join(STATE_DIR, "etsy_tokens.json")

ETSY_CLIENT_ID = os.getenv("ETSY_CLIENT_ID")
ETSY_REDIRECT_URI = os.getenv("ETSY_REDIRECT_URI", "http://localhost:8080/callback")

PRINTFUL_TOKEN = os.getenv("PRINTFUL_TOKEN")

LISTINGS_PER_RUN = int(os.getenv("LISTINGS_PER_RUN", "10"))
GEO = os.getenv("GEO", "US")
NICHE_SEED = [s.strip() for s in os.getenv("NICHE_SEED", "").split(",") if s.strip()]

SUBREDDITS = ["popular", "memes", "funny", "AskReddit", "sports", "Parenting", "mommit", "daddit"]

# Keep phrases printable + shirt-front friendly
MIN_LEN, MAX_LEN = 6, 48
PRINTABLE_RE = re.compile(r"^[A-Za-z0-9&'’\-\s\.\!\?]+$")

# Basic safety filters
PROFANITY = {"fuck", "shit", "bitch", "asshole", "cunt"}
POLITICS = {"trump", "biden", "maga", "democrat", "republican", "election"}
TRADEMARK_HINTS = ["disney", "marvel", "star wars", "pokemon", "nintendo", "harry potter", "nba", "nfl", "mlb"]

# Etsy API
ETSY_API_BASE = "https://api.etsy.com/v3/application"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"

# Printful API v2 catalog
PRINTFUL_V2_BASE = "https://api.printful.com/v2"

# Product choice: Gildan 18000 crewneck
TARGET_BRAND = "Gildan"
TARGET_MODEL_HINT = "18000"

# Variations we’ll offer on Etsy
OFFER_SIZES = ["S", "M", "L", "XL", "2XL", "3XL"]
OFFER_COLORS = ["Black", "Navy", "Maroon", "Forest Green", "Sport Grey"]

# Pricing on Etsy (Etsy wants price in cents in inventory update)
BASE_PRICE_USD = 32.99


# -----------------------------
# Helpers
# -----------------------------
def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)

def normalize(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

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
# Trend Intake (Google Trends + Reddit)
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

    return fuzzy_dedupe(terms, 93)[:120]

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
    phrases = []
    phrases += google_trends_terms(seed_terms)
    phrases += reddit_terms()
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
# Etsy OAuth + Shop ID resolve
# -----------------------------
def load_tokens():
    if not os.path.exists(TOKENS_PATH):
        return None
    return json.load(open(TOKENS_PATH, "r", encoding="utf-8"))

def save_tokens(tokens: Dict[str, Any]):
    json.dump(tokens, open(TOKENS_PATH, "w", encoding="utf-8"), indent=2)

def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge

def start_oauth(scopes: List[str]) -> Dict[str, Any]:
    if not ETSY_CLIENT_ID:
        raise RuntimeError("Missing ETSY_CLIENT_ID in .env")

    app = Flask(__name__)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    result = {"tokens": None, "error": None}

    auth_url = (
        "https://www.etsy.com/oauth/connect?"
        + urlencode({
            "response_type": "code",
            "redirect_uri": ETSY_REDIRECT_URI,
            "scope": " ".join(scopes),
            "client_id": ETSY_CLIENT_ID,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
    )

    print("\n1) Open this URL in your browser and approve:\n")
    print(auth_url)
    print("\n2) Etsy must redirect back to EXACTLY:")
    print(ETSY_REDIRECT_URI)
    print("\nWaiting for /callback...\n")

    @app.route("/")
    def root():
        return "OK. Waiting for Etsy OAuth callback at /callback"

    @app.route("/callback")
    def callback():
        code = request.args.get("code")
        got_state = request.args.get("state")

        if got_state != state:
            result["error"] = "State mismatch"
            return "State mismatch", 400
        if not code:
            result["error"] = "No code provided"
            return "No code provided", 400

        data = {
            "grant_type": "authorization_code",
            "client_id": ETSY_CLIENT_ID,
            "redirect_uri": ETSY_REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        }

        r = requests.post(ETSY_TOKEN_URL, data=data, timeout=30)
        if r.status_code != 200:
            result["error"] = f"Token exchange failed: {r.status_code} {r.text}"
            return result["error"], 400

        result["tokens"] = r.json()

        # Shut down Flask dev server after success
        func = request.environ.get("werkzeug.server.shutdown")
        if func:
            func()

        return "Authorized. You can close this tab."

    # Bind to localhost to match redirect URI (recommended)
    app.run(host="localhost", port=8080, debug=False)

    if result["error"]:
        raise RuntimeError(result["error"])
    if not result["tokens"]:
        raise RuntimeError("OAuth failed / no tokens received. Etsy never called /callback.")
    return result["tokens"]

def refresh_etsy_token(refresh_token: str) -> Dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "client_id": ETSY_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    r = requests.post(ETSY_TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    return r.json()

def get_access_token() -> str:
    tokens = load_tokens()
    if not tokens:
        scopes = ["listings_r", "listings_w", "shops_r"]
        tokens = start_oauth(scopes)
        save_tokens(tokens)
        return tokens["access_token"]

    if "refresh_token" in tokens:
        newt = refresh_etsy_token(tokens["refresh_token"])
        if "refresh_token" not in newt:
            newt["refresh_token"] = tokens["refresh_token"]
        save_tokens(newt)
        return newt["access_token"]

    return tokens["access_token"]

def etsy_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": ETSY_CLIENT_ID,
        "Accept": "application/json",
    }

def extract_user_id_from_access_token(access_token: str) -> int:
    # Etsy access_token format: "{user_id}.{opaque_token...}"
    if "." not in access_token:
        raise RuntimeError("Unexpected access_token format (missing user_id prefix).")
    return int(access_token.split(".", 1)[0])

def resolve_shop_id(access_token: str) -> int:
    user_id = extract_user_id_from_access_token(access_token)
    url = f"{ETSY_API_BASE}/users/{user_id}/shops"
    r = requests.get(url, headers=etsy_headers(access_token), timeout=30)
    r.raise_for_status()
    data = r.json()
    results = data.get("results") or data.get("shops") or []
    if not results:
        raise RuntimeError("No shops returned for this Etsy user. Are you authorizing the correct Etsy account?")
    shop_id = results[0].get("shop_id") or results[0].get("shopId") or results[0].get("id")
    if not shop_id:
        raise RuntimeError(f"Could not read shop_id from response: {data}")
    return int(shop_id)


# -----------------------------
# Printful (discover Gildan 18000 variant ids)
# -----------------------------
def printful_headers() -> Dict[str, str]:
    if not PRINTFUL_TOKEN:
        raise RuntimeError("Missing PRINTFUL_TOKEN in .env")
    return {"Authorization": f"Bearer {PRINTFUL_TOKEN}", "Accept": "application/json"}

def printful_find_gildan18000_product_id() -> int:
    limit = 100
    offset = 0
    while True:
        r = requests.get(
            f"{PRINTFUL_V2_BASE}/catalog-products",
            headers=printful_headers(),
            params={"limit": limit, "offset": offset, "selling_region_name": "worldwide"},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        if not data:
            break

        for p in data:
            name = (p.get("name") or "")
            brand = (p.get("brand") or "")
            if (TARGET_BRAND.lower() in brand.lower()
                and TARGET_MODEL_HINT in name
                and "Sweatshirt" in name
                and "Crew" in name):
                return int(p["id"])

        paging = r.json().get("paging", {})
        total = paging.get("total", 0)
        offset += limit
        if offset >= total:
            break

    raise RuntimeError("Could not find Gildan 18000 in Printful catalog-products listing.")

def printful_get_variants(product_id: int) -> List[Dict[str, Any]]:
    r = requests.get(
        f"{PRINTFUL_V2_BASE}/catalog-products/{product_id}/catalog-variants",
        headers=printful_headers(),
        params={"limit": 100, "offset": 0},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("data", [])

def build_variant_map_gildan18000() -> Dict[Tuple[str, str], int]:
    pid = printful_find_gildan18000_product_id()
    variants = printful_get_variants(pid)

    mapping: Dict[Tuple[str, str], int] = {}
    for v in variants:
        vid = int(v.get("id"))
        color = None
        size = None

        if isinstance(v.get("color"), dict):
            color = v["color"].get("name")
        elif isinstance(v.get("color"), str):
            color = v["color"]

        if isinstance(v.get("size"), str):
            size = v["size"]

        attrs = v.get("attributes")
        if isinstance(attrs, dict):
            color = color or attrs.get("color")
            size = size or attrs.get("size")

        color = normalize(color or "")
        size = normalize(size or "")

        if color and size:
            mapping[(color, size)] = vid

    filtered: Dict[Tuple[str, str], int] = {}
    for c in OFFER_COLORS:
        for s in OFFER_SIZES:
            best_vid = None
            best_score = 0
            for (vc, vs), vid in mapping.items():
                cs = fuzz.ratio(vc.lower(), c.lower())
                ss = fuzz.ratio(vs.lower(), s.lower())
                score = cs + ss
                if score > best_score:
                    best_score = score
                    best_vid = vid
            if best_vid and best_score >= 150:
                filtered[(c, s)] = best_vid

    missing = [(c, s) for c in OFFER_COLORS for s in OFFER_SIZES if (c, s) not in filtered]
    if missing:
        print("WARNING: Some (color,size) combos not found in Printful catalog mapping:")
        print(missing)

    return filtered


# -----------------------------
# Mockup generation (Pillow)
# -----------------------------
def load_font(size: int) -> ImageFont.ImageFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    words = text.split()
    lines = []
    cur = ""
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

def make_mockup_images(phrase: str) -> List[str]:
    stamp = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9]+", "_", phrase).strip("_")[:40]
    paths = []

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

    p1 = os.path.join(OUT_DIR, f"{stamp}_{safe}_01.png")
    img.save(p1, "PNG")
    paths.append(p1)

    img2 = Image.new("RGB", (2000, 2000), "white")
    d2 = ImageDraw.Draw(img2)
    font2 = load_font(180)
    lines2 = wrap_text(d2, phrase, font2, max_width=1500)
    y = 900 - (len(lines2) * 100)
    for line in lines2[:4]:
        w = d2.textlength(line, font=font2)
        d2.text(((2000 - w) / 2, y), line, fill="black", font=font2)
        y += 220

    p2 = os.path.join(OUT_DIR, f"{stamp}_{safe}_02.png")
    img2.save(p2, "PNG")
    paths.append(p2)

    img3 = Image.new("RGB", (2000, 2000), "white")
    d3 = ImageDraw.Draw(img3)
    d3.text((80, 80), "SIZE CHART (Gildan 18000)", fill="black", font=load_font(90))
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
    x0, y0 = 120, 300
    colw = [400, 600, 600]
    d3.text((x0, y0), headers[0], fill="black", font=load_font(70))
    d3.text((x0 + colw[0], y0), headers[1], fill="black", font=load_font(70))
    d3.text((x0 + colw[0] + colw[1], y0), headers[2], fill="black", font=load_font(70))

    y = y0 + 120
    font_row = load_font(64)
    for rrow in rows:
        d3.text((x0, y), rrow[0], fill="black", font=font_row)
        d3.text((x0 + colw[0], y), rrow[1], fill="black", font=font_row)
        d3.text((x0 + colw[0] + colw[1], y), rrow[2], fill="black", font=font_row)
        y += 110

    p3 = os.path.join(OUT_DIR, f"{stamp}_{safe}_03.png")
    img3.save(p3, "PNG")
    paths.append(p3)

    return paths


# -----------------------------
# Etsy listing + inventory
# -----------------------------
def etsy_create_draft_listing(access_token: str, shop_id: int, title: str, description: str, taxonomy_id: int) -> int:
    url = f"{ETSY_API_BASE}/shops/{shop_id}/listings"
    payload = {
        "title": title[:140],
        "description": description,
        "who_made": "someone_else",
        "when_made": "made_to_order",
        "taxonomy_id": taxonomy_id,
        "is_supply": False,
        "type": "physical",
        "quantity": 999,
        "price": f"{BASE_PRICE_USD:.2f}",
    }
    r = requests.post(url, headers=etsy_headers(access_token), json=payload, timeout=60)
    r.raise_for_status()
    j = r.json()
    return int(j.get("listing_id") or j.get("listingId"))

def etsy_patch_listing(access_token: str, shop_id: int, listing_id: int, patch: Dict[str, Any]) -> None:
    url = f"{ETSY_API_BASE}/shops/{shop_id}/listings/{listing_id}"
    r = requests.patch(url, headers=etsy_headers(access_token), json=patch, timeout=60)
    r.raise_for_status()

def etsy_upload_image(access_token: str, shop_id: int, listing_id: int, image_path: str, rank: int) -> None:
    url = f"{ETSY_API_BASE}/shops/{shop_id}/listings/{listing_id}/images"
    with open(image_path, "rb") as f:
        files = {"image": f}
        data = {"rank": str(rank)}
        r = requests.post(url, headers=etsy_headers(access_token), files=files, data=data, timeout=120)
        r.raise_for_status()

def etsy_update_inventory(access_token: str, listing_id: int, products: List[Dict[str, Any]]) -> None:
    url = f"{ETSY_API_BASE}/listings/{listing_id}/inventory"
    payload = {"products": products}
    r = requests.put(url, headers=etsy_headers(access_token), json=payload, timeout=120)
    r.raise_for_status()


# -----------------------------
# Taxonomy + Property IDs (Size/Color)
# -----------------------------
def etsy_get_seller_taxonomy_nodes(access_token: str) -> Dict[str, Any]:
    url = f"{ETSY_API_BASE}/seller-taxonomy/nodes"
    r = requests.get(url, headers=etsy_headers(access_token), timeout=60)
    r.raise_for_status()
    return r.json()

def etsy_get_properties_by_taxonomy_id(access_token: str, taxonomy_id: int) -> Dict[str, Any]:
    url = f"{ETSY_API_BASE}/seller-taxonomy/nodes/{taxonomy_id}/properties"
    r = requests.get(url, headers=etsy_headers(access_token), timeout=60)
    r.raise_for_status()
    return r.json()

def pick_taxonomy_id_for_sweatshirt(access_token: str) -> int:
    data = etsy_get_seller_taxonomy_nodes(access_token)
    nodes = data.get("results") or data.get("nodes") or []
    for n in nodes:
        name = (n.get("name") or "").lower()
        if "sweatshirt" in name:
            best = n.get("id") or n.get("taxonomy_id")
            if best:
                return int(best)
    return 691  # fallback

def find_property_ids(access_token: str, taxonomy_id: int) -> Tuple[int, int]:
    props = etsy_get_properties_by_taxonomy_id(access_token, taxonomy_id)
    results = props.get("results") or props.get("properties") or []
    size_pid = None
    color_pid = None
    for p in results:
        pname = (p.get("name") or p.get("property_name") or "").lower()
        pid = p.get("property_id") or p.get("id")
        if not pid:
            continue
        if size_pid is None and ("size" == pname or "sizes" in pname):
            size_pid = int(pid)
        if color_pid is None and ("color" in pname or "colour" in pname):
            color_pid = int(pid)
    if size_pid is None or color_pid is None:
        raise RuntimeError(f"Could not determine size/color property IDs for taxonomy_id={taxonomy_id}.")
    return size_pid, color_pid


# -----------------------------
# Listing content generator
# -----------------------------
def build_listing_assets(phrase: str) -> Dict[str, Any]:
    title = f"{phrase} Crewneck Sweatshirt, Funny {phrase} Sweatshirt, Unisex Heavy Blend, Gift Idea"
    tags = [
        phrase.lower()[:20],
        "crewneck",
        "sweatshirt",
        "heavy blend",
        "unisex",
        "gift idea",
        "sports mom",
        "game day",
        "practice life",
        "carpool",
        "coffee lover",
        "weekend vibes",
        "cozy",
    ]
    tags = [t[:20] for t in tags][:13]

    desc = f"""{phrase}

COZY UNISEX CREWNECK (Gildan 18000 style)
• Soft, warm, classic fit
• Printed to order
• Great for busy sports families, weekend life, and everyday comfort

SIZING
See size chart in listing photos.

PRODUCTION & SHIPPING
Made to order. Tracking provided when shipped.

NOTES
Colors may vary slightly due to screen settings.
"""

    materials = ["cotton", "polyester"]
    return {"title": title, "description": desc, "tags": tags, "materials": materials}

def build_etsy_inventory_products(
    size_pid: int,
    color_pid: int,
    variant_map: Dict[Tuple[str, str], int],
    readiness_state_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    products = []
    price_cents = int(round(BASE_PRICE_USD * 100))

    for color in OFFER_COLORS:
        for size in OFFER_SIZES:
            pf_vid = variant_map.get((color, size))
            if not pf_vid:
                continue

            sku = f"FS-G18000-{pf_vid}-{color[:3].upper()}-{size}"

            pv = [
                {"property_id": size_pid, "property_name": "Size", "value_ids": [], "values": [size]},
                {"property_id": color_pid, "property_name": "Color", "value_ids": [], "values": [color]},
            ]

            offering = {"price": price_cents, "quantity": 999, "is_enabled": True}
            if readiness_state_id is not None:
                offering["readiness_state_id"] = readiness_state_id

            products.append({"sku": sku, "property_values": pv, "offerings": [offering]})

    if not products:
        raise RuntimeError("No products were generated for Etsy inventory (variant mapping likely failed).")

    return products


# -----------------------------
# Main publisher
# -----------------------------
def publish_weekly():
    ensure_dirs()

    access_token = get_access_token()
    shop_id = resolve_shop_id(access_token)
    print(f"Using Etsy shop_id = {shop_id}")

    taxonomy_id = pick_taxonomy_id_for_sweatshirt(access_token)
    size_pid, color_pid = find_property_ids(access_token, taxonomy_id)

    variant_map = build_variant_map_gildan18000()

    top = pick_top_phrases()
    stamp = dt.date.today().isoformat()
    pd.DataFrame(top, columns=["phrase", "score"]).to_csv(os.path.join(OUT_DIR, f"{stamp}_top10.csv"), index=False)

    for idx, (phrase, score) in enumerate(top, start=1):
        phrase_clean = normalize(phrase)

        assets = build_listing_assets(phrase_clean)
        listing_id = etsy_create_draft_listing(access_token, shop_id, assets["title"], assets["description"], taxonomy_id)

        etsy_patch_listing(access_token, shop_id, listing_id, {"tags": assets["tags"], "materials": assets["materials"]})

        imgs = make_mockup_images(phrase_clean)
        for rnk, img_path in enumerate(imgs, start=1):
            etsy_upload_image(access_token, shop_id, listing_id, img_path, rank=rnk)

        products = build_etsy_inventory_products(size_pid=size_pid, color_pid=color_pid, variant_map=variant_map)
        etsy_update_inventory(access_token, listing_id, products)

        etsy_patch_listing(access_token, shop_id, listing_id, {"state": "active"})

        print(f"[{idx}/{len(top)}] ACTIVE listing_id={listing_id} | phrase={phrase_clean}")

    print("Done: published weekly top listings.")

if __name__ == "__main__":
    publish_weekly()