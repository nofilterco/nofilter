import os
import time
import re
import zlib
import requests
from typing import Dict, List, Any, Optional

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


def req(method: str, path: str, *, payload=None, params=None, timeout: int = 60):
    url = f"{BASE}{path}"
    r = requests.request(method, url, headers=headers(), json=payload, params=params, timeout=timeout)
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:
            body = r.text
        die(f"HTTP {r.status_code} for {method} {path}\nResponse: {body}")
    return r.json() if r.content else {}


def get_shop_id() -> int:
    shops = req("GET", "/shops.json")
    shop_id = int(os.getenv("PRINTIFY_SHOP_ID", "0"))
    if not shop_id:
        die("Missing PRINTIFY_SHOP_ID in .env")
    if not any(int(s.get("id")) == shop_id for s in shops):
        die(f"Shop ID {shop_id} not found under this token. Shops returned: {shops}")
    return shop_id


def upload_image_by_url(file_name: str, url: str) -> str:
    payload = {"file_name": file_name, "url": url}
    res = req("POST", "/uploads/images.json", payload=payload)
    return res["id"]


def find_hat_blueprint() -> int:
    override = (os.getenv("PRINTIFY_HAT_BLUEPRINT_ID") or "").strip()
    if override.isdigit():
        return int(override)

    blueprints = req("GET", "/catalog/blueprints.json")
    preferred = ["dad hat", "baseball", "cap", "hat", "trucker", "snapback", "embroidered"]

    def score(title: str) -> int:
        t = (title or "").lower()
        return sum(1 for k in preferred if k in t)

    best = None
    for bp in blueprints:
        title = bp.get("title", "")
        s = score(title)
        if best is None or s > best[0]:
            best = (s, bp)

    if not best or best[0] < 1:
        die("Could not confidently find a hat blueprint. Set PRINTIFY_HAT_BLUEPRINT_ID.")
    return int(best[1]["id"])


def pick_print_provider(blueprint_id: int) -> int:
    providers = req("GET", f"/catalog/blueprints/{blueprint_id}/print_providers.json")
    if isinstance(providers, dict) and "data" in providers:
        providers = providers["data"]
    if not isinstance(providers, list) or not providers:
        die(f"No print providers returned for blueprint_id={blueprint_id}")

    override = (os.getenv("PRINTIFY_HAT_PROVIDER_ID") or "").strip()
    if override.isdigit():
        return int(override)

    for p in providers:
        if "united states" in str(p.get("location", "")).lower():
            return int(p["id"])
    return int(providers[0]["id"])


def get_variants(blueprint_id: int, provider_id: int) -> List[Dict[str, Any]]:
    res = req("GET", f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")

    if isinstance(res, list):
        return res

    if isinstance(res, dict):
        # ✅ Your observed shape: {'id':..., 'title':..., 'variants':[...]}
        if isinstance(res.get("variants"), list):
            return res["variants"]

        for key in ("data", "items", "results"):
            val = res.get(key)
            if isinstance(val, list):
                return val

        die(f"Unexpected variants response shape. Keys={list(res.keys())}")

    die(f"Unexpected variants response type: {type(res)}")


def _parse_csv_env(name: str) -> List[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("&", "and")
    s = re.sub(r"\s+", " ", s)
    return s


def _variant_match_blob(v: Dict[str, Any]) -> str:
    title = _norm(str(v.get("title") or ""))
    options = v.get("options") or {}
    color = _norm(str(options.get("color") or options.get("colors") or ""))
    return f"{title} | {color}"


def choose_hat_variant_ids(variants: List[Dict[str, Any]], *, seed_key: str = "") -> List[int]:
    """
    Hats usually have One size; variants are colors.

    Default behavior:
      - enables Top-5 common sellers: Black, Navy, Charcoal, Khaki, White (single colors)
      - optionally rotates which of those becomes the FIRST variant (Shopify default image)
        using a stable seed_key (e.g. row id / product title)
    """
    override_ids = _parse_csv_env("PRINTIFY_HAT_VARIANT_IDS")
    if override_ids:
        out = [int(x) for x in override_ids if x.strip().isdigit()]
        if out:
            return out

    # Top-5 popular single-color choices
    desired = _parse_csv_env("HAT_TOP_COLORS")
    if not desired:
        desired = ["black", "navy", "charcoal", "khaki", "white"]

    rotate = (os.getenv("HAT_ROTATE_DEFAULT", "0").strip().lower() in ("1", "true", "yes", "y", "on"))
    if rotate and desired:
        if seed_key:
            shift = zlib.crc32(seed_key.encode("utf-8")) % len(desired)
        else:
            shift = int(time.time()) % len(desired)
        desired = desired[shift:] + desired[:shift]

    picked: List[int] = []
    for want in desired:
        want_n = _norm(want)
        for v in variants:
            vid = v.get("id")
            if not vid:
                continue
            blob = _variant_match_blob(v)
            # match whole word-ish
            if re.search(rf"\b{re.escape(want_n)}\b", blob):
                vid_i = int(vid)
                if vid_i not in picked:
                    picked.append(vid_i)
                break

    # Fallback: just enable first 5 variants
    if not picked:
        picked = [int(v["id"]) for v in variants[:5] if v.get("id")]

    return picked


def create_hat_product(
    shop_id: int,
    title: str,
    description: str,
    tags: List[str],
    blueprint_id: int,
    provider_id: int,
    variant_ids: List[int],
    image_id: str,
    price_cents: int,
):
    url = f"{BASE}/shops/{shop_id}/products.json"

    # Keep variant order (Shopify often uses first variant as default)
    variants_payload = [{"id": vid, "price": price_cents, "is_enabled": True} for vid in variant_ids]

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
                                "scale": float(os.getenv("HAT_ART_SCALE", "1.0")),
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

    r = requests.post(url, headers=headers(), json=payload, timeout=60)
    if not r.ok:
        die(f"Product creation failed: {r.text}")
    return r.json()["id"]


def publish_product(shop_id: int, product_id: str):
    payload = {
        "title": True,
        "description": True,
        "images": True,
        "variants": True,
        "tags": True,
        "keyFeatures": True,
        "shipping_template": True,
    }
    req("POST", f"/shops/{shop_id}/products/{product_id}/publish.json", payload=payload)