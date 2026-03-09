from __future__ import annotations

import os
from typing import Any

import requests

SHOP_URL = os.getenv("SHOPIFY_STORE_URL", "")
TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN", "")


def _headers() -> dict[str, str]:
    return {
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return f"https://{SHOP_URL}/admin/api/2024-01"


def add_to_collection(product_id: int, collection_id: int) -> None:
    url = f"{_base_url()}/collects.json"
    payload = {"collect": {"product_id": product_id, "collection_id": collection_id}}
    requests.post(url, headers=_headers(), json=payload, timeout=30)


def find_product_id_by_title(title: str) -> str:
    if not SHOP_URL or not TOKEN or not title:
        return ""
    url = f"{_base_url()}/products.json"
    params = {"title": title, "limit": 1, "fields": "id,title"}
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        products = resp.json().get("products", [])
        if products:
            return str(products[0].get("id", ""))
    except Exception:
        return ""
    return ""
