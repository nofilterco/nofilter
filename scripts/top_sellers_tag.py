"""Tag top-selling products in Shopify based on order line items.

Requires env:
  SHOPIFY_STORE_DOMAIN (e.g. yourstore.myshopify.com)
  SHOPIFY_ADMIN_TOKEN  (Admin API access token)
  SHOPIFY_API_VERSION  (default 2024-07)

Usage:
  python scripts/top_sellers_tag.py --days 30 --top 10 --tag top-seller

Notes:
- Shopify doesn't expose 'sales' per product directly in Products API.
- This script scans Orders within a date window and counts product_id occurrences.
"""
import os, argparse, datetime, collections, requests

def _die(msg: str):
    raise SystemExit(f"\n❌ {msg}\n")

def _headers():
    token = os.getenv("SHOPIFY_ADMIN_TOKEN")
    if not token:
        _die("Missing SHOPIFY_ADMIN_TOKEN")
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

def _base():
    dom = os.getenv("SHOPIFY_STORE_DOMAIN")
    if not dom:
        _die("Missing SHOPIFY_STORE_DOMAIN")
    ver = os.getenv("SHOPIFY_API_VERSION", "2024-07")
    return f"https://{dom}/admin/api/{ver}"

def _get(path, params=None):
    url = _base() + path
    r = requests.get(url, headers=_headers(), params=params, timeout=60)
    if r.status_code >= 400:
        _die(f"GET {path} failed: {r.status_code} {r.text[:500]}")
    return r.json()

def _put(path, payload):
    url = _base() + path
    r = requests.put(url, headers=_headers(), json=payload, timeout=60)
    if r.status_code >= 400:
        _die(f"PUT {path} failed: {r.status_code} {r.text[:500]}")
    return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--tag", type=str, default="top-seller")
    args = ap.parse_args()

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=args.days)).isoformat() + "Z"
    counts = collections.Counter()

    page_info = None
    fetched = 0

    # Simple pagination via 'since_id' fallback (works fine for low volume)
    since_id = 0
    while True:
        data = _get("/orders.json", params={
            "status": "any",
            "limit": 250,
            "created_at_min": since,
            "since_id": since_id,
        })
        orders = data.get("orders") or []
        if not orders:
            break
        for o in orders:
            since_id = max(since_id, int(o.get("id") or 0))
            for li in (o.get("line_items") or []):
                pid = li.get("product_id")
                if pid:
                    counts[int(pid)] += int(li.get("quantity") or 1)
        fetched += len(orders)
        if len(orders) < 250:
            break

    top = counts.most_common(args.top)
    print(f"Scanned {fetched} orders since {since}. Top products: {top}")

    for pid, qty in top:
        prod = _get(f"/products/{pid}.json").get("product") or {}
        tags = set(t.strip() for t in (prod.get("tags") or "").split(",") if t.strip())
        if args.tag not in tags:
            tags.add(args.tag)
            payload = {"product": {"id": pid, "tags": ", ".join(sorted(tags))}}
            _put(f"/products/{pid}.json", payload)
            print(f"Tagged product {pid} ({qty} sold) with '{args.tag}'")
        else:
            print(f"Product {pid} already tagged")

if __name__ == "__main__":
    main()
