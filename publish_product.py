from __future__ import annotations

import json
import os
from typing import Any

from printify_catalog import create_product, publish_product as printify_publish


def resolve_profile(row: dict[str, str], profile: dict[str, Any]) -> dict[str, Any]:
    row["product_family"] = profile.get("product_family", "")
    row["shopify_product_type"] = profile.get("default_shopify_product_type", "")
    row["personalization_mode"] = profile.get("personalization_capability", "none")
    hints = profile.get("printify_blueprint_hints", {})
    if not row.get("printify_blueprint_id"):
        row["printify_blueprint_id"] = str(hints.get("blueprint_id", ""))
    if not row.get("printify_provider_id"):
        row["printify_provider_id"] = str(hints.get("provider_id", ""))
    return row


def resolve_variants(row: dict[str, str]) -> dict[str, str]:
    row["variant_strategy"] = row.get("variant_strategy") or "curated_launch"
    row["enabled_variant_ids_json"] = row.get("enabled_variant_ids_json") or "[]"
    return row


def build_printify_payload(row: dict[str, str]) -> dict[str, Any]:
    tags = [t.strip() for t in (row.get("tags_csv") or "").split(",") if t.strip()]
    return {
        "title": row["title"],
        "description": row["description_html"],
        "blueprint_id": int(row["printify_blueprint_id"] or 0),
        "print_provider_id": int(row["printify_provider_id"] or 0),
        "tags": tags,
        "variants": [{"id": int(v), "price": int(row["price_cents"] or 0), "is_enabled": True} for v in json.loads(row.get("enabled_variant_ids_json") or "[]")],
        "print_areas": [],
    }


def publish_listing(row: dict[str, str]) -> dict[str, str]:
    shop_id = os.getenv("PRINTIFY_SHOP_ID", "")
    if not shop_id:
        row["error_message"] = "PRINTIFY_SHOP_ID missing"
        return row
    payload = build_printify_payload(row)
    created = create_product(shop_id, payload)
    row["printify_product_id"] = str(created.get("id", ""))
    if row["publish_mode"] in ("personalized", "both"):
        row["needs_manual_personalization_setup"] = "YES"
    if row["printify_product_id"]:
        printify_publish(shop_id, row["printify_product_id"])
        row["status"] = "PUBLISHED"
    return row
