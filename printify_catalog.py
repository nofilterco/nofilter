from __future__ import annotations

import os
import requests
from typing import Any

BASE = "https://api.printify.com/v1"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.getenv('PRINTIFY_TOKEN','')}", "Content-Type": "application/json"}


def _get(path: str) -> Any:
    r = requests.get(f"{BASE}{path}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path: str, payload: dict[str, Any]) -> Any:
    r = requests.post(f"{BASE}{path}", headers=_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def discover_blueprints() -> list[dict[str, Any]]:
    data = _get("/catalog/blueprints.json")
    return data if isinstance(data, list) else []


def discover_variants(blueprint_id: int, provider_id: int) -> list[dict[str, Any]]:
    data = _get(f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")
    return data.get("variants", data if isinstance(data, list) else [])


def create_product(shop_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _post(f"/shops/{shop_id}/products.json", payload)


def publish_product(shop_id: str, product_id: str) -> dict[str, Any]:
    return _post(f"/shops/{shop_id}/products/{product_id}/publish.json", {"title": True, "description": True, "images": True, "variants": True, "tags": True})
