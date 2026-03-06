import os
import re
import json
import time
import argparse
import requests
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
SHOPIFY_STORE_DOMAIN = (os.getenv("SHOPIFY_STORE_DOMAIN") or "").strip()
SHOPIFY_ADMIN_TOKEN = (os.getenv("SHOPIFY_ADMIN_TOKEN") or "").strip()
SHOPIFY_API_VERSION = (os.getenv("SHOPIFY_API_VERSION") or "2024-10").strip()
BRAND_NAME = (os.getenv("BRAND_NAME") or "No Filter Co").strip()

SHOPIFY_STORE_DOMAIN = SHOPIFY_STORE_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")

client = OpenAI(api_key=OPENAI_API_KEY)

os.makedirs("product_csv", exist_ok=True)
os.makedirs("designs", exist_ok=True)
os.makedirs("scripts", exist_ok=True)
os.makedirs("trend_research", exist_ok=True)

OUT_PRODUCTS = "product_csv/products.csv"
OUT_PROMPTS = "designs/design_prompts.csv"
OUT_MARKETING = "scripts/marketing_content.csv"

DEFAULT_PRICE = {
    "T-Shirt": 29.99,
    "Hoodie": 49.99,
    "Mug": 19.99,
    "Sticker": 4.99,
}
DEFAULT_COMPARE = {
    "T-Shirt": 39.99,
    "Hoodie": 69.99,
    "Mug": 24.99,
    "Sticker": 6.99,
}

def die(msg: str):
    raise SystemExit(f"\n❌ {msg}\n")

def gql_url():
    if "myshopify.com" not in SHOPIFY_STORE_DOMAIN:
        die("SHOPIFY_STORE_DOMAIN must be like yourstore.myshopify.com (no https, no trailing /).")
    return f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

def gql_headers():
    if not SHOPIFY_ADMIN_TOKEN.startswith("shpat_"):
        die("SHOPIFY_ADMIN_TOKEN must start with shpat_. You currently have the wrong token type.")
    return {
        "X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

def shopify_graphql(query: str, variables: dict | None = None) -> dict:
    payload = {"query": query, "variables": variables or {}}
    r = requests.post(gql_url(), headers=gql_headers(), data=json.dumps(payload))
    if r.status_code == 429:
        time.sleep(2)
        return shopify_graphql(query, variables)
    if r.status_code != 200:
        raise RuntimeError(f"Shopify GraphQL HTTP {r.status_code}: {r.text[:800]}")
    data = r.json()
    if "errors" in data and data["errors"]:
        raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")
    return data

def test_shopify():
    q = """
    query {
      shop { name myshopifyDomain }
    }
    """
    data = shopify_graphql(q)
    shop = data["data"]["shop"]
    print("✅ Connected to Shopify:")
    print("Shop:", shop["name"])
    print("Domain:", shop["myshopifyDomain"])

def extract_json(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"```(?:json)?", "", text, flags=re.I).replace("```", "").strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    return m.group(0).strip() if m else ""

def generate_phrases(n=20):
    prompt = f"""
Generate {n} short, original, trendy slang/culture phrases for merchandise for a brand called "{BRAND_NAME}".
Rules:
- 2–6 words.
- No brand names, no celebrities, no copyrighted catchphrases.
- Must be safe to print and sell.
Return as plain list, one per line, no numbering.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.9
    )
    lines = (resp.choices[0].message.content or "").splitlines()
    phrases = []
    seen = set()
    for line in lines:
        p = line.strip().lstrip("-•").strip()
        if not p:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(p)
    return phrases[:n]

def generate_product_json(phrase: str) -> dict:
    prompt = f"""
Return ONLY valid JSON (no markdown) for phrase: "{phrase}"

Schema:
{{
 "title": "string",
 "description": "80-140 words, no emojis",
 "bullets": ["5 short bullets"],
 "tags": ["8-12 lowercase tags, 1-3 words"]
}}
"""
    # Force JSON
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.7,
        response_format={"type":"json_object"},
    )
    return json.loads(resp.choices[0].message.content or "{}")

def design_prompt(phrase: str) -> str:
    return (
        f'Minimalist typography design.\n'
        f'Phrase: "{phrase}"\n'
        f'Vibe: internet culture / clean streetwear.\n'
        f'Black and white.\n'
        f'Centered composition.\n'
        f'Transparent background.\n'
        f'4500x5400px, print-ready.\n'
    )

def marketing_copy(phrase: str) -> str:
    prompt = f"""
Create:
- 2 TikTok hooks (1 line each)
- 1 Instagram caption (1-2 sentences)
- 1 email launch announcement (6-10 sentences)
For phrase: "{phrase}"
No emojis.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0.9
    )
    return resp.choices[0].message.content or ""

def build_rows(phrases, product_types):
    product_rows = []
    prompt_rows = []
    marketing_rows = []

    for phrase in phrases:
        pj = generate_product_json(phrase)
        title_base = (pj.get("title") or phrase).strip()
        desc = (pj.get("description") or "").strip()
        bullets = pj.get("bullets") or []
        bullets = [str(b).strip() for b in bullets][:5]
        while len(bullets) < 5:
            bullets.append("Comfortable everyday fit.")
        tags = pj.get("tags") or []
        tags = [str(t).strip().lower() for t in tags if str(t).strip()]
        tags = tags[:12] if tags else ["trend","slang","streetwear","viral"]

        body_html = "<p>" + desc + "</p><ul>" + "".join([f"<li>{b}</li>" for b in bullets]) + "</ul>"

        for ptype in product_types:
            product_rows.append({
                "Title": f"{title_base} — {ptype}",
                "Body (HTML)": body_html,
                "Vendor": BRAND_NAME,
                "Type": ptype,
                "Tags": ", ".join(tags),
                "Price": DEFAULT_PRICE.get(ptype, 29.99),
                "CompareAt": DEFAULT_COMPARE.get(ptype, None),
                "Status": "DRAFT",
            })

        prompt_rows.append({"phrase": phrase, "design_prompt": design_prompt(phrase).strip()})
        marketing_rows.append({"phrase": phrase, "marketing": marketing_copy(phrase).strip()})

        print(f"✅ Built: {title_base}")

    return product_rows, prompt_rows, marketing_rows

def cmd_generate(args):
    product_types = args.types.split(",")
    product_types = [t.strip() for t in product_types if t.strip()]
    phrases = generate_phrases(args.count)

    products, prompts, marketing = build_rows(phrases, product_types)

    pd.DataFrame(products).to_csv(OUT_PRODUCTS, index=False)
    pd.DataFrame(prompts).to_csv(OUT_PROMPTS, index=False)
    pd.DataFrame(marketing).to_csv(OUT_MARKETING, index=False)

    print("\n✅ Wrote:")
    print(" -", OUT_PRODUCTS)
    print(" -", OUT_PROMPTS)
    print(" -", OUT_MARKETING)

def shopify_create_product_draft(row: dict) -> dict:
    title = row["Title"]
    body_html = row["Body (HTML)"]
    vendor = row["Vendor"]
    ptype = row["Type"]
    tags = row.get("Tags","")
    price = float(row.get("Price", 29.99))
    compare_at = row.get("CompareAt", None)

    mutation = """
    mutation productCreate($input: ProductInput!) {
      productCreate(input: $input) {
        product { id handle status title }
        userErrors { field message }
      }
    }
    """

    input_obj = {
        "title": title,
        "descriptionHtml": body_html,
        "vendor": vendor,
        "productType": ptype,
        "status": "DRAFT",
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "variants": [{
            "price": str(price),
        }]
    }
    if compare_at and str(compare_at).strip() not in ("", "None"):
        input_obj["variants"][0]["compareAtPrice"] = str(compare_at)

    data = shopify_graphql(mutation, {"input": input_obj})
    pc = data["data"]["productCreate"]
    errs = pc["userErrors"]
    if errs:
        raise RuntimeError(f"productCreate userErrors for '{title}': {errs}")
    return pc["product"]

def cmd_upload_shopify(args):
    if not os.path.exists(OUT_PRODUCTS):
        die(f"Missing {OUT_PRODUCTS}. Run: generate first.")

    df = pd.read_csv(OUT_PRODUCTS)
    created = []

    for idx, row in df.iterrows():
        title = row["Title"]
        print(f"[{idx+1}/{len(df)}] Creating draft: {title}")
        product = shopify_create_product_draft(row.to_dict())
        created.append({
            "Title": title,
            "ShopifyID": product["id"],
            "Handle": product["handle"],
            "Status": product["status"],
        })
        time.sleep(0.6)

    out = "product_csv/shopify_created_products.csv"
    pd.DataFrame(created).to_csv(out, index=False)
    print("\n✅ Uploaded drafts. Log:", out)

def cmd_weekly_drop(args):
    # Simple weekly: generate + upload
    cmd_generate(args)
    cmd_upload_shopify(args)

def cmd_margins(args):
    # Placeholder margin calculator (edit Printful costs later)
    if not os.path.exists(OUT_PRODUCTS):
        die(f"Missing {OUT_PRODUCTS}. Run: generate first.")
    df = pd.read_csv(OUT_PRODUCTS)

    # Example base costs (replace with Printful cost sheet later)
    base_cost = {
        "T-Shirt": 14.00,
        "Hoodie": 26.00,
        "Mug": 8.50,
        "Sticker": 1.50,
    }

    rows = []
    for _, r in df.iterrows():
        ptype = r["Type"]
        price = float(r["Price"])
        cost = base_cost.get(ptype, 10.00)
        gross = price - cost
        margin = gross / price if price else 0
        # Simple "ad safe" heuristic: margin >= 55%
        ad_safe = "YES" if margin >= 0.55 else "NO"
        rows.append({
            "Title": r["Title"],
            "Type": ptype,
            "Price": price,
            "EstCost": cost,
            "GrossProfit": round(gross, 2),
            "GrossMargin": round(margin, 3),
            "AdSafe": ad_safe
        })

    out = "product_csv/margins_report.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print("✅ Margin report:", out)

def main():
    p = argparse.ArgumentParser("nofilterco")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("test-shopify")

    g = sub.add_parser("generate")
    g.add_argument("--count", type=int, default=20)
    g.add_argument("--types", type=str, default="T-Shirt,Hoodie,Mug,Sticker")

    sub.add_parser("upload-shopify")

    w = sub.add_parser("weekly-drop")
    w.add_argument("--count", type=int, default=15)
    w.add_argument("--types", type=str, default="T-Shirt,Hoodie,Mug")

    sub.add_parser("margins")

    args = p.parse_args()

    if args.cmd == "test-shopify":
        test_shopify()
    elif args.cmd == "generate":
        cmd_generate(args)
    elif args.cmd == "upload-shopify":
        cmd_upload_shopify(args)
    elif args.cmd == "weekly-drop":
        cmd_weekly_drop(args)
    elif args.cmd == "margins":
        cmd_margins(args)
    else:
        die("Unknown command")

if __name__ == "__main__":
    main()