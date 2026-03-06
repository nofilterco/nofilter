import os, re, json, time, base64, hashlib, secrets, sqlite3
import datetime as dt
from urllib.parse import urlencode

import requests
import pandas as pd
from dotenv import load_dotenv
from rapidfuzz import fuzz
from pytrends.request import TrendReq
import praw
from flask import Flask, request

load_dotenv()

OUT_DIR = "out"
STATE_DIR = "state"
TOKENS_PATH = os.path.join(STATE_DIR, "tokens.json")
DB_PATH = os.path.join(STATE_DIR, "mappings.sqlite")

ETSY_CLIENT_ID = os.getenv("ETSY_CLIENT_ID")
ETSY_REDIRECT_URI = os.getenv("ETSY_REDIRECT_URI", "http://localhost:8080/callback")
ETSY_SHOP_ID = os.getenv("ETSY_SHOP_ID")
PRINTFUL_TOKEN = os.getenv("PRINTFUL_TOKEN")

GEO = os.getenv("GEO", "US")
LISTINGS_PER_RUN = int(os.getenv("LISTINGS_PER_RUN", "10"))
NICHE_SEED = [s.strip() for s in os.getenv("NICHE_SEED", "").split(",") if s.strip()]

SUBREDDITS = ["popular", "memes", "funny", "AskReddit", "sports", "Parenting", "mommit", "daddit"]
MIN_LEN, MAX_LEN = 6, 48
PRINTABLE_RE = re.compile(r"^[A-Za-z0-9&'’\-\s\.\!\?]+$")

PROFANITY = {"fuck","shit","bitch","asshole","cunt"}
POLITICS = {"trump","biden","maga","democrat","republican","election"}
TRADEMARK_HINTS = ["disney","marvel","star wars","pokemon","nintendo","harry potter","nba","nfl","mlb"]

ETSY_API_BASE = "https://openapi.etsy.com/v3/application"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"

# ---------------------------
# State
# ---------------------------
def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)

def load_tokens():
    if not os.path.exists(TOKENS_PATH):
        return None
    return json.load(open(TOKENS_PATH, "r", encoding="utf-8"))

def save_tokens(tokens):
    json.dump(tokens, open(TOKENS_PATH, "w", encoding="utf-8"), indent=2)

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS order_map (
        etsy_receipt_id TEXT PRIMARY KEY,
        printful_order_id TEXT,
        status TEXT,
        created_at TEXT
      )
    """)
    con.commit()
    con.close()

# ---------------------------
# Etsy OAuth (one-time browser step)
# ---------------------------
def pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge

def start_oauth_server_and_get_tokens(scopes):
    """
    Opens an authorization URL you click once.
    Etsy uses OAuth 2.0 auth code grant. :contentReference[oaicite:7]{index=7}
    """
    app = Flask(__name__)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)

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

    print("\n1) Open this URL in your browser and approve:")
    print(auth_url)
    print("\n2) After approval, Etsy redirects to your redirect URI.\n")

    result = {"tokens": None, "error": None}

    @app.route("/callback")
    def callback():
        code = request.args.get("code")
        got_state = request.args.get("state")
        if got_state != state:
            result["error"] = "State mismatch"
            return "State mismatch", 400

        # exchange code for token
        data = {
            "grant_type": "authorization_code",
            "client_id": ETSY_CLIENT_ID,
            "redirect_uri": ETSY_REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        }
        r = requests.post(ETSY_TOKEN_URL, data=data, timeout=30)
        r.raise_for_status()
        result["tokens"] = r.json()
        return "Authorized. You can close this tab."

    # Run local server briefly
    host = "127.0.0.1"
    port = 8080
    print(f"Listening on {host}:{port} for OAuth callback...")
    app.run(host=host, port=port)

    if result["error"]:
        raise RuntimeError(result["error"])
    if not result["tokens"]:
        raise RuntimeError("OAuth failed.")
    return result["tokens"]

def refresh_etsy_token(refresh_token):
    data = {
        "grant_type": "refresh_token",
        "client_id": ETSY_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    r = requests.post(ETSY_TOKEN_URL, data=data, timeout=30)
    r.raise_for_status()
    return r.json()

def etsy_headers(access_token):
    return {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": ETSY_CLIENT_ID,
        "Accept": "application/json",
    }

# ---------------------------
# Trend intake
# ---------------------------
def normalize(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s

def is_printable(s: str) -> bool:
    return bool(PRINTABLE_RE.match(s))

def flags_for(phrase: str):
    f = []
    if not is_printable(phrase): f.append("non_printable")
    if not (MIN_LEN <= len(phrase) <= MAX_LEN): f.append("length")
    words = set(re.findall(r"[a-z]+", phrase.lower()))
    if words & PROFANITY: f.append("profanity")
    if words & POLITICS: f.append("politics")
    if any(h in phrase.lower() for h in TRADEMARK_HINTS): f.append("trademark_hint")
    return f

def fuzzy_dedupe(items, threshold=92):
    kept = []
    for it in items:
        it = normalize(it)
        if not it: continue
        if any(fuzz.token_sort_ratio(it.lower(), k.lower()) >= threshold for k in kept):
            continue
        kept.append(it)
    return kept

def google_trends_terms(seed_terms):
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

    terms = fuzzy_dedupe(terms, 93)
    return terms[:80]

def reddit_terms():
    cid = os.getenv("REDDIT_CLIENT_ID")
    csec = os.getenv("REDDIT_CLIENT_SECRET")
    ua = os.getenv("REDDIT_USER_AGENT", "trend_intake/1.0")
    if not cid or not csec:
        return []

    reddit = praw.Reddit(client_id=cid, client_secret=csec, user_agent=ua)
    terms = []
    for sub in SUBREDDITS:
        try:
            for post in reddit.subreddit(sub).hot(limit=50):
                t = normalize(post.title)
                if t:
                    # take segment after ":" too (often meme payload)
                    if ":" in t:
                        terms.append(normalize(t.split(":",1)[1]))
                    terms.append(t)
        except Exception:
            continue
    terms = [t for t in terms if is_printable(t) and MIN_LEN <= len(t) <= MAX_LEN]
    return fuzzy_dedupe(terms, 92)

def rank_phrases(phrases):
    # Simple rank: shorter + “shirt-ready” gets boosted
    ranked = []
    for p in phrases:
        L = len(p)
        score = 0
        if 10 <= L <= 28: score += 10
        elif 29 <= L <= 40: score += 4
        else: score -= 2
        if "!" in p or "?" in p: score += 2
        ranked.append((p, score, flags_for(p)))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked

# ---------------------------
# Etsy listing generation
# ---------------------------
def generate_listing_pack(phrase: str):
    # SEO-ish title patterns (keep under Etsy limits; you’ll tune)
    title = f"{phrase} Shirt, Funny {phrase} Tee, Gift Idea, Unisex Softstyle"
    tags = [
        phrase.lower(),
        "funny shirt", "unisex tee", "gift idea", "everyday wear",
        "mom life", "sports mom", "game day", "practice life",
        "carpool", "coffee lover", "weekend vibes", "minimal style"
    ]
    tags = [t[:20] for t in tags][:13]  # Etsy tags are max 20 chars, 13 tags

    description = f"""\
{phrase}

• Unisex fit, super soft
• Printed to order (made just for you)
• Great gift for moms, sports families, and busy weekends

SIZING
See size chart in photos.

PRODUCTION & SHIPPING
Made to order. Tracking provided when shipped.

NOTES
Colors may vary slightly due to screen settings.
"""

    # You will set these to match Etsy allowed values:
    # who_made: i_did / someone_else / collective
    # when_made: made_to_order
    # is_supply: false
    return {
        "title": title[:140],
        "description": description,
        "tags": tags,
        "who_made": "someone_else",
        "when_made": "made_to_order",
        "is_supply": False,
        "taxonomy_id": 0,  # TODO: set a real taxonomy_id for shirts
        "price": "24.99",
        "quantity": 999,
    }

# ---------------------------
# Etsy API actions (create listing, upload images, inventory, publish)
# ---------------------------
def etsy_create_draft_listing(access_token, pack):
    # Docs/tutorials: listings are created as draft and then activated. :contentReference[oaicite:8]{index=8}
    url = f"{ETSY_API_BASE}/shops/{ETSY_SHOP_ID}/listings"
    payload = {
        "title": pack["title"],
        "description": pack["description"],
        "who_made": pack["who_made"],
        "when_made": pack["when_made"],
        "taxonomy_id": pack["taxonomy_id"],
        "is_supply": pack["is_supply"],
        "price": pack["price"],
        "quantity": pack["quantity"],
        "type": "physical",
    }
    r = requests.post(url, headers=etsy_headers(access_token), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def etsy_upload_listing_image(access_token, listing_id, image_path, rank=1):
    url = f"{ETSY_API_BASE}/shops/{ETSY_SHOP_ID}/listings/{listing_id}/images"
    files = {"image": open(image_path, "rb")}
    data = {"rank": str(rank)}
    r = requests.post(url, headers=etsy_headers(access_token), files=files, data=data, timeout=60)
    r.raise_for_status()
    return r.json()

def etsy_update_listing_tags(access_token, listing_id, tags):
    url = f"{ETSY_API_BASE}/shops/{ETSY_SHOP_ID}/listings/{listing_id}"
    r = requests.patch(url, headers=etsy_headers(access_token), json={"tags": tags}, timeout=30)
    r.raise_for_status()
    return r.json()

def etsy_activate_listing(access_token, listing_id):
    url = f"{ETSY_API_BASE}/shops/{ETSY_SHOP_ID}/listings/{listing_id}"
    r = requests.patch(url, headers=etsy_headers(access_token), json={"state": "active"}, timeout=30)
    r.raise_for_status()
    return r.json()

# ---------------------------
# Printful fulfillment
# ---------------------------
def printful_headers():
    return {"Authorization": f"Bearer {PRINTFUL_TOKEN}", "Content-Type": "application/json"}

def printful_create_order(order_payload):
    # Printful Orders API: create orders for fulfillment. :contentReference[oaicite:9]{index=9}
    r = requests.post("https://api.printful.com/orders", headers=printful_headers(), json=order_payload, timeout=60)
    r.raise_for_status()
    return r.json()

# ---------------------------
# Orders: Etsy -> Printful -> Etsy tracking
# ---------------------------
def etsy_get_receipts(access_token, min_created=None):
    url = f"{ETSY_API_BASE}/shops/{ETSY_SHOP_ID}/receipts"
    params = {}
    if min_created:
        params["min_created"] = int(min_created)
    r = requests.get(url, headers=etsy_headers(access_token), params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def etsy_create_receipt_shipment(access_token, receipt_id, carrier_name, tracking_code):
    # Etsy fulfillment tutorial: createReceiptShipment posts tracking. :contentReference[oaicite:10]{index=10}
    url = f"{ETSY_API_BASE}/shops/{ETSY_SHOP_ID}/receipts/{receipt_id}/tracking"
    payload = {"carrier_name": carrier_name, "tracking_code": tracking_code}
    r = requests.post(url, headers=etsy_headers(access_token), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

# ---------------------------
# Main
# ---------------------------
def get_access_token():
    tokens = load_tokens()
    if not tokens:
        scopes = [
            # listing management + receipts + fulfillment + transactions
            # you will prune/adjust to your needs
            "listings_r", "listings_w",
            "transactions_r",
            "shops_r",
            "receipts_r", "receipts_w",
        ]
        tokens = start_oauth_server_and_get_tokens(scopes)
        save_tokens(tokens)
        return tokens["access_token"]

    # refresh if possible
    if "refresh_token" in tokens:
        newt = refresh_etsy_token(tokens["refresh_token"])
        # preserve refresh_token if Etsy doesn’t always return it
        if "refresh_token" not in newt and "refresh_token" in tokens:
            newt["refresh_token"] = tokens["refresh_token"]
        save_tokens(newt)
        return newt["access_token"]

    return tokens["access_token"]

def run_publish_10():
    access_token = get_access_token()

    seed_terms = NICHE_SEED or ["game day","sports mom","practice","carpool","coffee"]
    phrases = []
    phrases += google_trends_terms(seed_terms)
    phrases += reddit_terms()

    ranked = rank_phrases(fuzzy_dedupe(phrases, 92))

    # Keep “clean” phrases only (you can also keep flagged and review)
    clean = [(p,s,f) for (p,s,f) in ranked if not set(f) & {"profanity","politics","trademark_hint"}]

    top10 = clean[:LISTINGS_PER_RUN]
    stamp = dt.date.today().isoformat()
    pd.DataFrame(top10, columns=["phrase","score","flags"]).to_csv(
        os.path.join(OUT_DIR, f"{stamp}_top10.csv"), index=False
    )

    for i, (phrase, score, flags) in enumerate(top10, start=1):
        pack = generate_listing_pack(phrase)

        # TODO: generate mockups to disk (or render simple text mockups)
        # For now, you must provide at least one image file path per listing.
        # Replace with your mockup generator output.
        image_path = "templates/placeholder_mockup.jpg"

        listing = etsy_create_draft_listing(access_token, pack)
        listing_id = listing.get("listing_id") or listing.get("listingId")
        if not listing_id:
            raise RuntimeError(f"Could not read listing_id from response: {listing}")

        etsy_update_listing_tags(access_token, listing_id, pack["tags"])
        etsy_upload_listing_image(access_token, listing_id, image_path, rank=1)

        # TODO: inventory/variants endpoint call here (sizes/colors)
        # Etsy inventory endpoints exist in v3 reference; wire them in once you decide product model. :contentReference[oaicite:11]{index=11}

        etsy_activate_listing(access_token, listing_id)
        print(f"[{i}/{len(top10)}] Published listing {listing_id}: {phrase}")

def main():
    ensure_dirs()
    init_db()
    run_publish_10()
    print("Done.")

if __name__ == "__main__":
    main()