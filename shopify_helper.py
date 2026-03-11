from __future__ import annotations

import os
from typing import Any

import requests

def _headers() -> dict[str, str]:
    token = os.getenv("SHOPIFY_ADMIN_TOKEN", "")
    return {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    shop_url = os.getenv("SHOPIFY_STORE_URL", "")
    return f"https://{shop_url}/admin/api/2024-01"


def add_to_collection(product_id: int, collection_id: int) -> None:
    url = f"{_base_url()}/collects.json"
    payload = {"collect": {"product_id": product_id, "collection_id": collection_id}}
    requests.post(url, headers=_headers(), json=payload, timeout=30)


def find_product_id_by_title(title: str) -> str:
    if not os.getenv("SHOPIFY_STORE_URL", "") or not os.getenv("SHOPIFY_ADMIN_TOKEN", "") or not title:
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


def find_product_by_handle(handle: str) -> dict[str, Any]:
    if not os.getenv("SHOPIFY_STORE_URL", "") or not os.getenv("SHOPIFY_ADMIN_TOKEN", "") or not handle:
        return {}
    url = f"{_base_url()}/products.json"
    params = {"handle": handle, "limit": 1, "fields": "id,title,handle"}
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        products = resp.json().get("products", [])
        return products[0] if products else {}
    except Exception:
        return {}
