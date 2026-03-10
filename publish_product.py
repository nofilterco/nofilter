from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from printify_catalog import (
    PrintifyAPIError,
    create_product,
    get_product,
    list_shops,
    publish_product as printify_publish,
    upload_image,
)
from shopify_helper import find_product_by_handle, find_product_id_by_title

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if row.get("product_family") == "tote":
        unresolved = []
        if not row.get("printify_blueprint_id"):
            unresolved.append("blueprint")
        if not row.get("printify_provider_id"):
            unresolved.append("provider")
        matched = ((profile.get("full_catalog_metadata") or {}).get("matched_variant_ids") or []) if isinstance(profile, dict) else []
        if not matched:
            unresolved.append("variants")
        if unresolved:
            row["launch_status"] = "BLOCKED_PROFILE"
            row["error_stage"] = "PROFILE"
            row["printify_publish_status"] = "BLOCKED_PROFILE"
            row["shopify_sync_status"] = "BLOCKED_PROFILE"
            row["error_message"] = f"Unresolved tote profile metadata: missing {', '.join(unresolved)}."
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
    enabled_sizes = set(json.loads(row.get("enabled_sizes_json") or "[]"))
    enabled_colors = set(json.loads(row.get("enabled_colors_json") or "[]"))
    in_stock_only = (row.get("in_stock_only") or "").upper() == "YES"

    if variant_records and parsed_ids:
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
            stock_ok = True if not in_stock_only else bool(item.get("is_available", item.get("is_enabled", True)))
            if size_ok and color_ok and stock_ok:
                filtered.append(vid)
        if filtered:
            parsed_ids = filtered

    row["enabled_variant_ids_json"] = json.dumps(parsed_ids)
    if not parsed_ids:
        row["error_stage"] = "PUBLISH"
        row["error_message"] = "No Printify variant IDs resolved from profile metadata using active size/color/stock rules."
    return row


def _ensure_printify_image_id(row: dict[str, str]) -> str:
    if row.get("printify_image_id"):
        return row["printify_image_id"]
    if not os.getenv("PRINTIFY_SHOP_ID", "").strip():
        row["printify_image_id"] = row.get("printify_image_id") or f"mock-image-{row.get('id','0')}"
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
    payload: dict[str, Any] = {
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
    sales_channel_collections = [v.strip() for v in (row.get("shopify_sales_channel_collections") or "").split(",") if v.strip()]
    if sales_channel_collections:
        payload["sales_channel_properties"] = {"shopify": {"collections": sales_channel_collections}}
    return payload




def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
    area_count = len(payload.get("print_areas") or [])
    return {
        "title": payload.get("title", ""),
        "blueprint_id": payload.get("blueprint_id"),
        "print_provider_id": payload.get("print_provider_id"),
        "variant_count": len(variants),
        "variant_ids_sample": [v.get("id") for v in variants[:5] if isinstance(v, dict)],
        "print_area_count": area_count,
        "tag_count": len(payload.get("tags") or []),
    }


def validate_printify_shop_access(shop_id: str) -> tuple[bool, str]:
    if not shop_id:
        return False, "PRINTIFY_SHOP_ID is missing."
    shops = list_shops()
    visible_ids = {str(shop.get("id", "")) for shop in shops if isinstance(shop, dict)}
    if shop_id not in visible_ids:
        return False, f"PRINTIFY_SHOP_ID {shop_id} is not visible for the active PRINTIFY_TOKEN."
    return True, ""


def _set_publish_failure(row: dict[str, str], *, stage: str, message: str, response: dict[str, Any] | None = None) -> None:
    row["error_stage"] = stage
    row["error_message"] = message
    row["printify_publish_status"] = "PUBLISH_FAILED"
    row["status"] = "PUBLISH_FAILED"
    row["launch_status"] = "PUBLISH_FAILED"
    row["last_publish_response"] = json.dumps(response or {"error": message}, ensure_ascii=False)[:5000]

def _sync_status_check(row: dict[str, str], shop_id: str) -> None:
    row["last_sync_check_at"] = now_iso()
    if not row.get("printify_product_id"):
        row["shopify_sync_status"] = "NOT_ATTEMPTED"
        return
    try:
        product = get_product(shop_id, row["printify_product_id"])
        visible = bool(product.get("visible"))
        row["shopify_sync_status"] = "SYNC_PENDING" if visible else "SYNC_PENDING"
    except Exception:
        row["shopify_sync_status"] = "NOT_ATTEMPTED"

    shopify_id = row.get("shopify_product_id") or ""
    if not shopify_id and row.get("shopify_handle"):
        product = find_product_by_handle(row.get("shopify_handle", ""))
        shopify_id = str(product.get("id", ""))
        if product.get("handle"):
            row["shopify_handle"] = str(product["handle"])
    if not shopify_id:
        shopify_id = find_product_id_by_title(row.get("title", ""))
    if shopify_id:
        row["shopify_product_id"] = shopify_id
        row["shopify_sync_status"] = "SYNCED_TO_SHOPIFY"



def recheck_sync_for_row(row: dict[str, str]) -> dict[str, str]:
    shop_id = os.getenv("PRINTIFY_SHOP_ID", "").strip()
    row["last_sync_check_at"] = now_iso()
    if not shop_id:
        if row.get("shopify_product_id"):
            row["shopify_sync_status"] = "SYNCED_TO_SHOPIFY"
        else:
            row["shopify_sync_status"] = "SYNC_PENDING"
        row["error_stage"] = row.get("error_stage") or "CONFIG"
        row["error_message"] = row.get("error_message") or "PRINTIFY_SHOP_ID missing for sync check"
        return row
    _sync_status_check(row, shop_id)
    return row

def publish_listing(row: dict[str, str], *, dry_run: bool = False, debug: bool = False) -> dict[str, str]:
    if row.get("launch_status") == "BLOCKED_PROFILE" or row.get("product_family") == "tote":
        row["error_stage"] = row.get("error_stage") or "PROFILE"
        row["launch_status"] = "BLOCKED_PROFILE"
        row["status"] = "BLOCKED_PROFILE"
        row["error_message"] = row.get("error_message") or "Tote publishing blocked: unresolved blueprint/provider/variant profile metadata."
        row["printify_publish_status"] = "BLOCKED_PROFILE"
        row["shopify_sync_status"] = "NOT_ATTEMPTED"
        return row

    payload = build_printify_payload(row)
    payload_summary = _payload_summary(payload)
    row["_last_printify_payload"] = json.dumps(payload, ensure_ascii=False)
    if dry_run:
        row["printify_publish_status"] = "NOT_ATTEMPTED"
        return row

    shop_id = os.getenv("PRINTIFY_SHOP_ID", "").strip()
    if not shop_id:
        row["printify_product_id"] = row.get("printify_product_id") or f"mock-printify-{row.get('id','0')}"
        row["last_publish_response"] = json.dumps({"mock": True, "reason": "PRINTIFY_SHOP_ID missing", "id": row["printify_product_id"]})
        row["printify_publish_status"] = "PUBLISHED_TO_PRINTIFY"
        row["shopify_sync_status"] = "SYNC_PENDING"
        row["status"] = "PUBLISHED_TO_PRINTIFY"
        row["launch_status"] = "PUBLISHED_TO_PRINTIFY"
        return row

    try:
        created = create_product(shop_id, payload)
        row["printify_product_id"] = str(created.get("id", ""))
        row["last_publish_response"] = json.dumps(created, ensure_ascii=False)[:5000]
        row["printify_publish_status"] = "PUBLISHED_TO_PRINTIFY" if row["printify_product_id"] else "PUBLISH_FAILED"
        if row.get("publish_mode") in ("personalized", "both"):
            row["needs_manual_personalization_setup"] = "YES"
        if row["printify_product_id"]:
            publish_resp = printify_publish(shop_id, row["printify_product_id"])
            row["last_publish_response"] = json.dumps(publish_resp, ensure_ascii=False)[:5000]
            row["printify_publish_status"] = "PUBLISHED_TO_PRINTIFY"
            _sync_status_check(row, shop_id)
            row["status"] = "PUBLISHED_TO_PRINTIFY"
            row["launch_status"] = "PUBLISHED_TO_PRINTIFY"
            row["error_stage"] = ""
            row["error_message"] = ""
        else:
            _set_publish_failure(row, stage="PUBLISH", message="Printify create_product returned no id")
    except PrintifyAPIError as exc:
        response = {
            "method": exc.method or "POST",
            "url": f"https://api.printify.com/v1{exc.path or f'/shops/{shop_id}/products.json'}",
            "status": exc.status_code,
            "body": exc.response_body,
            "payload_summary": payload_summary,
        }
        _set_publish_failure(row, stage="PRINTIFY_API", message=str(exc), response=response)
    except Exception as exc:
        response = {"error": str(exc), "payload_summary": payload_summary}
        _set_publish_failure(row, stage="PUBLISH", message=f"Unexpected publish error: {exc}", response=response)

    if debug:
        print(json.dumps({
            "listing_slug": row.get("listing_slug", ""),
            "printify_publish_status": row.get("printify_publish_status", ""),
            "error_stage": row.get("error_stage", ""),
            "error_message": row.get("error_message", ""),
            "last_publish_response": row.get("last_publish_response", ""),
            "payload_summary": payload_summary,
        }, ensure_ascii=False, indent=2))
    return row
