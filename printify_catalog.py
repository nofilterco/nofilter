from __future__ import annotations

import base64
import json
import os
import requests
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

BASE = "https://api.printify.com/v1"

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


class PrintifyAPIError(RuntimeError):
    """Raised when Printify returns a non-2xx response with rich diagnostics."""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.getenv('PRINTIFY_TOKEN','')}", "Content-Type": "application/json"}


def _get(path: str) -> Any:
    r = requests.get(f"{BASE}{path}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path: str, payload: dict[str, Any]) -> Any:
    r = requests.post(f"{BASE}{path}", headers=_headers(), json=payload, timeout=30)
    if r.status_code >= 400:
        body: Any
        try:
            body = r.json()
        except Exception:
            body = r.text
        body_text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        raise PrintifyAPIError(f"Printify POST {path} failed with status {r.status_code}: {body_text}")
    return r.json()


def discover_blueprints() -> list[dict[str, Any]]:
    data = _get("/catalog/blueprints.json")
    return data if isinstance(data, list) else []


def discover_variants(blueprint_id: int, provider_id: int) -> list[dict[str, Any]]:
    data = _get(f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")
    return data.get("variants", data if isinstance(data, list) else [])


def create_product(shop_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _post(f"/shops/{shop_id}/products.json", payload)


def upload_image(file_name: str, *, url: str = "", local_path: str = "") -> dict[str, Any]:
    if url:
        return _post("/uploads/images.json", {"file_name": file_name, "url": url})
    if local_path:
        encoded = base64.b64encode(open(local_path, "rb").read()).decode("utf-8")
        return _post("/uploads/images.json", {"file_name": file_name, "contents": encoded})
    raise ValueError("upload_image requires either url or local_path")


def publish_product(shop_id: str, product_id: str) -> dict[str, Any]:
    return _post(f"/shops/{shop_id}/products/{product_id}/publish.json", {"title": True, "description": True, "images": True, "variants": True, "tags": True})
