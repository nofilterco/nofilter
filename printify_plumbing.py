import os
import sys
import time
import requests
from typing import Any, Dict, List, Optional

BASE_URL = "https://api.printify.com/v1"
TOKEN_ENV = "PRINTIFY_TOKEN"

def _rate_limit_snapshot(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Printify may or may not return rate-limit headers.
    This collects common ones if present.
    """
    interesting = [
        "RateLimit",  # emerging standard some APIs use
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "Retry-After",
    ]
    return {k: v for k, v in headers.items() if k in interesting}

def _request(method: str, path: str, token: str, **kwargs) -> requests.Response:
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {})
    headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    return resp

def list_shops(token: str) -> List[Dict[str, Any]]:
    resp = _request("GET", "/shops.json", token)

    print(f"HTTP {resp.status_code} {resp.reason}")
    rl = _rate_limit_snapshot(resp.headers)
    print("Rate-limit headers (if any):", rl if rl else "(none found)")

    if resp.status_code == 401:
        raise RuntimeError("401 Unauthorized: check PRINTIFY_TOKEN (is it correct / active?).")
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        raise RuntimeError(f"429 Too Many Requests. Retry-After={retry_after}")
    resp.raise_for_status()

    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response shape (expected list). Got: {type(data)}")
    return data

def pick_shop(shops: List[Dict[str, Any]], hint: Optional[str] = None) -> Dict[str, Any]:
    """
    If you pass hint='shopify' (or part of your store name), we’ll pick the first match.
    Otherwise, we just return the first shop.
    """
    if not shops:
        raise RuntimeError("No shops returned for this token/account.")

    if hint:
        h = hint.lower()
        for s in shops:
            title = str(s.get("title", "")).lower()
            channel = str(s.get("sales_channel", "")).lower()
            if h in title or h in channel:
                return s

    return shops[0]

def main():
    token = os.getenv(TOKEN_ENV)
    if not token:
        print(f"Missing env var {TOKEN_ENV}. Example:")
        print(f'  export {TOKEN_ENV}="YOUR_PRINTIFY_PERSONAL_ACCESS_TOKEN"')
        sys.exit(1)

    hint = sys.argv[1] if len(sys.argv) > 1 else None

    shops = list_shops(token)

    print("\nShops:")
    for s in shops:
        print(f"  id={s.get('id')}  title={s.get('title')}  sales_channel={s.get('sales_channel')}")

    chosen = pick_shop(shops, hint=hint)
    print("\nChosen shop:")
    print(f"  SHOP_ID={chosen.get('id')}  title={chosen.get('title')}  sales_channel={chosen.get('sales_channel')}")

if __name__ == "__main__":
    main()