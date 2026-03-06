import os
import sys
import time
import json
import requests
from dotenv import load_dotenv

BASE = "https://api.printify.com/v1"

def die(msg: str, *, code: int = 1):
    print(f"\n❌ {msg}\n")
    raise SystemExit(code)

def headers():
    token = os.getenv("PRINTIFY_TOKEN")
    ua = os.getenv("USER_AGENT", "NoFilterCoBot/1.0")
    if not token:
        die("Missing PRINTIFY_TOKEN in .env")
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": ua,
        "Content-Type": "application/json",
    }

def req(method: str, path: str, *, payload=None, params=None):
    url = f"{BASE}{path}"
    r = requests.request(method, url, headers=headers(), json=payload, params=params, timeout=60)
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:
            body = r.text
        die(f"HTTP {r.status_code} for {method} {path}\nResponse: {body}")
    return r.json() if r.content else {}

def get_shop_id() -> int:
    # Optional sanity check: confirm shop exists for token
    shops = req("GET", "/shops.json")
    shop_id = int(os.getenv("PRINTIFY_SHOP_ID", "0"))
    if not shop_id:
        die("Missing PRINTIFY_SHOP_ID in .env")
    if not any(int(s.get("id")) == shop_id for s in shops):
        die(f"Shop ID {shop_id} not found under this token. Shops returned: {shops}")
    return shop_id

def upload_image_by_url(file_name: str, url: str) -> str:
    # Printify upload by URL
    # Docs show: { "file_name": "...png", "url": "http://..." } :contentReference[oaicite:6]{index=6}
    payload = {"file_name": file_name, "url": url}
    res = req("POST", "/uploads/images.json", payload=payload)
    return res["id"]

def find_tee_blueprint() -> int:
    # Pull catalog blueprints and pick a tee-like one.
    # We'll prefer Bella+Canvas 3001 if available, otherwise first “Unisex…Tee”.
    blueprints = req("GET", "/catalog/blueprints.json")
    preferred = [
        "bella", "canvas", "3001", "unisex", "jersey", "short sleeve", "t-shirt", "tee"
    ]

    def score(title: str) -> int:
        t = title.lower()
        return sum(1 for k in preferred if k in t)

    best = None
    for bp in blueprints:
        title = bp.get("title", "")
        s = score(title)
        if best is None or s > best[0]:
            best = (s, bp)

    if not best or best[0] < 2:
        die("Could not confidently find a tee blueprint from catalog/blueprints.json")
    return int(best[1]["id"])

def pick_print_provider(blueprint_id: int) -> int:
    providers = req(
        "GET",
        f"/catalog/blueprints/{blueprint_id}/print_providers.json"
    )

    # Handle wrapped or unwrapped responses
    if isinstance(providers, dict) and "data" in providers:
        providers = providers["data"]

    if not isinstance(providers, list) or len(providers) == 0:
        die(f"No print providers returned for blueprint_id={blueprint_id}")

    return int(providers[0]["id"])

def get_variants(blueprint_id: int, provider_id: int):
    res = req("GET", f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")

    # Common Printify shapes:
    # 1) {"data":[...]}
    if isinstance(res, dict) and "data" in res and isinstance(res["data"], list):
        return res["data"]

    # 2) {"id":..., "title":..., "variants":[...]}
    if isinstance(res, dict) and "variants" in res and isinstance(res["variants"], list):
        return res["variants"]

    # 3) direct list
    if isinstance(res, list):
        return res

    die(f"Unexpected variants response type={type(res)} value={res}")

def choose_variant_ids(variants, want_colors=("Black", "White"), want_sizes=("S", "M", "L", "XL"), max_count=12):
    picked = []

    for v in variants:
        if not isinstance(v, dict):
            continue

        opts = v.get("options") or {}
        color = (opts.get("color") or "").strip()
        size = (opts.get("size") or "").strip()

        # must support front print
        placeholders = v.get("placeholders") or []
        has_front = any(p.get("position") == "front" for p in placeholders if isinstance(p, dict))
        if not has_front:
            continue

        if color in want_colors and size in want_sizes:
            picked.append(int(v["id"]))
        if len(picked) >= max_count:
            break

    # fallback: first available with front
    if not picked:
        for v in variants:
            if not isinstance(v, dict) or "id" not in v:
                continue
            placeholders = v.get("placeholders") or []
            has_front = any(p.get("position") == "front" for p in placeholders if isinstance(p, dict))
            if has_front:
                picked.append(int(v["id"]))
            if len(picked) >= min(8, max_count):
                break

    if not picked:
        raise RuntimeError("No valid variants found (with front placeholder).")
    return picked

def create_product(
    shop_id,
    title,
    description,
    tags,
    blueprint_id,
    provider_id,
    variant_ids,
    image_id,
    price_cents,
):
    import requests
    from dotenv import load_dotenv
    import os

    load_dotenv()
    api_token = os.getenv("PRINTIFY_TOKEN")

    if not api_token:
        raise RuntimeError("Missing PRINTIFY_TOKEN in .env")

    url = f"https://api.printify.com/v1/shops/{shop_id}/products.json"

    variants_payload = [
        {
            "id": vid,
            "price": price_cents,
            "is_enabled": True,
        }
        for vid in variant_ids
    ]

    payload = {
        "title": title,
        "description": description,
        "blueprint_id": blueprint_id,
        "print_provider_id": provider_id,
        "variants": variants_payload,
        "print_areas": [
            {
                "variant_ids": variant_ids,
                "placeholders": [
                    {
                        "position": "front",
                        "images": [
                            {
                                "id": image_id,
                                "x": 0.5,
                                "y": 0.5,
                                "scale": 1,
                                "angle": 0,
                            }
                        ],
                    }
                ],
            }
        ],
        "tags": tags,
        "visible": True,
    }

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload)

    if not response.ok:
        print("❌ Product creation failed:", response.text)
        response.raise_for_status()

    return response.json()["id"]

def publish_product(shop_id: int, product_id: str):
    # Publish endpoint payload example from docs :contentReference[oaicite:8]{index=8}
    payload = {
        "title": True,
        "description": True,
        "images": True,
        "variants": True,
        "tags": True,
        "keyFeatures": True,
        "shipping_template": True
    }
    req("POST", f"/shops/{shop_id}/products/{product_id}/publish.json", payload=payload)

def main():
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python publish_tee.py <PUBLIC_PNG_URL> [title]")
        print("Example: python publish_tee.py https://<r2-public>/designs/test.png \"No Filter Co Tee\"")
        sys.exit(2)

    png_url = sys.argv[1].strip()
    title = sys.argv[2].strip() if len(sys.argv) >= 3 else "No Filter Co - Test Tee"
    shop_id = get_shop_id()

    print("✅ Shop verified:", shop_id)

    # Upload image
    print("⬆️ Uploading design to Printify media library (by URL)...")
    image_id = upload_image_by_url("design.png", png_url)
    print("✅ Uploaded image_id:", image_id)

    # Find tee blueprint + provider + variants
    print("🔎 Finding tee blueprint...")
    blueprint_id = find_tee_blueprint()
    print("✅ blueprint_id:", blueprint_id)

    print("🏭 Picking print provider...")
    provider_id = pick_print_provider(blueprint_id)
    print("✅ print_provider_id:", provider_id)

    print("🎛️ Loading variants...")
    variants = get_variants(blueprint_id, provider_id)
    
    variant_ids = choose_variant_ids(variants)
    print("✅ enabled variant_ids:", variant_ids)
    print("Variant sample:", json.dumps(variants[:2], indent=2) if isinstance(variants, list) else variants)

    # Create product
    description = "Soft unisex tee. Printed on demand and shipped by our production partner."
    tags = ["tees", "niche-test", "nofilterco"]
    price_cents = 1999  # $19.99

    print("🧱 Creating product draft...")
    product_id = create_product(
        shop_id=shop_id,
        title=title,
        description=description,
        tags=tags,
        blueprint_id=blueprint_id,
        provider_id=provider_id,
        variant_ids=variant_ids,
        image_id=image_id,
        price_cents=price_cents,
    )
    print("✅ Created product_id:", product_id)

    # Publish to Shopify
    print("🚀 Publishing to Shopify via Printify...")
    publish_product(shop_id, product_id)
    print("✅ Published. Check Shopify Products (may take a minute to appear).")

if __name__ == "__main__":
    main()