from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from printify_catalog import create_product, publish_product as printify_publish, upload_image

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def resolve_profile(row: dict[str, str], profile: dict[str, Any]) -> dict[str, Any]:
    row["product_family"] = profile.get("product_family", "")
    row["shopify_product_type"] = profile.get("default_shopify_product_type", "")
    row["personalization_mode"] = profile.get("personalization_capability", "none")
    hints = profile.get("printify_blueprint_hints", {})
    if not row.get("printify_blueprint_id"):
        row["printify_blueprint_id"] = str(hints.get("blueprint_id", ""))
    if not row.get("printify_provider_id"):
        row["printify_provider_id"] = str(hints.get("provider_id", ""))
    row["_placeholder_print_position"] = profile.get("placeholder_print_position", "front")
    return row


def resolve_variants(row: dict[str, str], profile: dict[str, Any]) -> dict[str, str]:
    row["variant_strategy"] = row.get("variant_strategy") or "curated_launch"
    if row.get("enabled_variant_ids_json") and row.get("enabled_variant_ids_json") != "[]":
        return row

    meta = profile.get("full_catalog_metadata") if isinstance(profile, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    ids = meta.get("matched_variant_ids") or meta.get("printify_variant_ids") or []
    parsed_ids = [int(v) for v in ids if str(v).strip().isdigit()]

    variant_records = meta.get("matched_variants") or meta.get("variants") or []
    if variant_records and parsed_ids:
        enabled_sizes = set(json.loads(row.get("enabled_sizes_json") or "[]"))
        enabled_colors = set(json.loads(row.get("enabled_colors_json") or "[]"))
        filtered: list[int] = []
        for item in variant_records:
            if not isinstance(item, dict):
                continue
            vid = item.get("id")
            if not isinstance(vid, int) or vid not in parsed_ids:
                continue
            options = item.get("options") if isinstance(item.get("options"), dict) else {}
            size_ok = not enabled_sizes or options.get("size") in enabled_sizes
            color_ok = not enabled_colors or options.get("color") in enabled_colors
            if size_ok and color_ok:
                filtered.append(vid)
        if filtered:
            parsed_ids = filtered

    row["enabled_variant_ids_json"] = json.dumps(parsed_ids)
    if not parsed_ids:
        row["error_stage"] = "PUBLISH"
        row["error_message"] = "No Printify variant IDs resolved from profile metadata (full_catalog_metadata.matched_variant_ids)."
    return row


def _ensure_printify_image_id(row: dict[str, str]) -> str:
    if row.get("printify_image_id"):
        return row["printify_image_id"]
    asset_url = (row.get("asset_r2_url") or "").strip()
    asset_local_path = (row.get("asset_local_path") or "").strip()
    file_name = f"{row.get('listing_slug','listing')}.png"
    if asset_url:
        uploaded = upload_image(file_name, url=asset_url)
    elif asset_local_path and Path(asset_local_path).exists():
        uploaded = upload_image(file_name, local_path=asset_local_path)
    else:
        raise RuntimeError("Missing listing asset; build assets first (asset_local_path/asset_r2_url missing)")
    row["printify_image_id"] = str(uploaded.get("id", ""))
    if not row["printify_image_id"]:
        raise RuntimeError(f"Printify image upload returned no id: {uploaded}")
    return row["printify_image_id"]


def build_printify_payload(row: dict[str, str]) -> dict[str, Any]:
    tags = [t.strip() for t in (row.get("tags_csv") or "").split(",") if t.strip()]
    variant_ids = [int(v) for v in json.loads(row.get("enabled_variant_ids_json") or "[]")]
    if not variant_ids:
        raise ValueError("No enabled variant ids resolved; refusing to call Printify create_product")
    image_id = _ensure_printify_image_id(row)
    print_position = row.get("_placeholder_print_position") or "front"
    return {
        "title": row["title"],
        "description": row["description_html"],
        "blueprint_id": int(row["printify_blueprint_id"] or 0),
        "print_provider_id": int(row["printify_provider_id"] or 0),
        "tags": tags,
        "variants": [{"id": int(v), "price": int(row["price_cents"] or 0), "is_enabled": True} for v in variant_ids],
        "print_areas": [{
            "variant_ids": variant_ids,
            "placeholders": [{
                "position": print_position,
                "images": [{"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}],
            }],
        }],
    }


def publish_listing(row: dict[str, str], *, dry_run: bool = False) -> dict[str, str]:
    payload = build_printify_payload(row)
    row["_last_printify_payload"] = json.dumps(payload, ensure_ascii=False)
    if dry_run:
        return row
    shop_id = os.getenv("PRINTIFY_SHOP_ID", "")
    if not shop_id:
        row["error_message"] = "PRINTIFY_SHOP_ID missing"
        return row
    created = create_product(shop_id, payload)
    row["printify_product_id"] = str(created.get("id", ""))
    if row["publish_mode"] in ("personalized", "both"):
        row["needs_manual_personalization_setup"] = "YES"
    if row["printify_product_id"]:
        printify_publish(shop_id, row["printify_product_id"])
        row["status"] = "PUBLISHED"
    return row
