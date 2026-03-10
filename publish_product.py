from __future__ import annotations

import json
import os
import time
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


def _parse_positive_int(value: Any) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else 0
    except Exception:
        return 0


def _profile_resolution_details(profile: dict[str, Any], row: dict[str, str]) -> tuple[bool, int, int, list[int], str]:
    hints = profile.get("printify_blueprint_hints") if isinstance(profile.get("printify_blueprint_hints"), dict) else {}
    meta = profile.get("full_catalog_metadata") if isinstance(profile.get("full_catalog_metadata"), dict) else {}
    blueprint_id = _parse_positive_int(row.get("printify_blueprint_id") or hints.get("blueprint_id"))
    provider_id = _parse_positive_int(row.get("printify_provider_id") or hints.get("provider_id"))
    raw_ids = meta.get("matched_variant_ids") or meta.get("printify_variant_ids") or []
    matched_ids = [_parse_positive_int(v) for v in raw_ids]
    matched_ids = [v for v in matched_ids if v > 0]

    missing: list[str] = []
    if blueprint_id <= 0:
        missing.append("blueprint")
    if provider_id <= 0:
        missing.append("provider")
    if not matched_ids:
        missing.append("variant IDs")

    return (len(missing) == 0), blueprint_id, provider_id, matched_ids, ", ".join(missing)


def resolve_profile(row: dict[str, str], profile: dict[str, Any]) -> dict[str, Any]:
    row["product_family"] = profile.get("product_family", "")
    row["shopify_product_type"] = profile.get("default_shopify_product_type", "")
    row["personalization_mode"] = profile.get("personalization_capability", "none")
    resolved, blueprint_id, provider_id, matched_ids, missing_parts = _profile_resolution_details(profile, row)

    row["printify_blueprint_id"] = str(blueprint_id) if blueprint_id > 0 else ""
    row["printify_provider_id"] = str(provider_id) if provider_id > 0 else ""
    row["profile_resolved"] = "YES" if resolved else "NO"
    row["blueprint_id"] = str(blueprint_id) if blueprint_id > 0 else "0"
    row["provider_id"] = str(provider_id) if provider_id > 0 else "0"
    row["matched_variant_count"] = str(len(matched_ids))
    row["_placeholder_print_position"] = profile.get("placeholder_print_position", "front")

    if not resolved:
        row["launch_status"] = "BLOCKED_PROFILE"
        row["status"] = "BLOCKED_PROFILE"
        row["error_stage"] = "PROFILE"
        row["printify_publish_status"] = "BLOCKED_PROFILE"
        row["shopify_sync_status"] = "BLOCKED_PROFILE"
        row["error_message"] = (
            "Unresolved profile metadata: blueprint/provider/variant IDs missing. "
            "Run Printify profile resolver."
        )
        row["last_publish_response"] = json.dumps({"missing": missing_parts}, ensure_ascii=False)
    return row


def resolve_variants(row: dict[str, str], profile: dict[str, Any]) -> dict[str, str]:
    row["variant_strategy"] = row.get("variant_strategy") or "curated_launch"

    if row.get("profile_resolved") == "NO":
        row["enabled_variant_ids_json"] = "[]"
        row["enabled_variant_count_before_filter"] = "0"
        row["enabled_variant_count_after_filter"] = "0"
        return row

    meta = profile.get("full_catalog_metadata") if isinstance(profile, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    ids = meta.get("matched_variant_ids") or meta.get("printify_variant_ids") or []
    parsed_ids = [_parse_positive_int(v) for v in ids]
    parsed_ids = [v for v in parsed_ids if v > 0]

    enabled_sizes = {str(v) for v in json.loads(row.get("enabled_sizes_json") or "[]") if str(v).strip()}
    enabled_colors = {str(v) for v in json.loads(row.get("enabled_colors_json") or "[]") if str(v).strip()}
    in_stock_only = (row.get("in_stock_only") or "").upper() == "YES"

    row["enabled_variant_count_before_filter"] = str(len(parsed_ids))

    variant_records = meta.get("matched_variants") or meta.get("variants") or []
    filtered_ids = list(parsed_ids)
    if isinstance(variant_records, list) and variant_records and parsed_ids:
        filtered: list[int] = []
        for item in variant_records:
            if not isinstance(item, dict):
                continue
            vid = _parse_positive_int(item.get("id"))
            if vid <= 0 or vid not in parsed_ids:
                continue
            options = item.get("options") if isinstance(item.get("options"), dict) else {}
            size_ok = not enabled_sizes or str(options.get("size", "")) in enabled_sizes
            color_ok = not enabled_colors or str(options.get("color", "")) in enabled_colors
            stock_ok = True if not in_stock_only else bool(item.get("is_available", item.get("is_enabled", True)))
            if size_ok and color_ok and stock_ok:
                filtered.append(vid)
        filtered_ids = filtered

    row["enabled_variant_ids_json"] = json.dumps(filtered_ids)
    row["enabled_variant_count_after_filter"] = str(len(filtered_ids))

    if not filtered_ids:
        row["error_stage"] = "PUBLISH"
        row["error_message"] = (
            "Resolved profile variant IDs found, but active size/color/stock rules reduced usable variants to zero."
        )
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


def _collect_error_strings(payload: Any, *, max_items: int = 8) -> list[str]:
    found: list[str] = []

    def walk(value: Any, path: str = "") -> None:
        if len(found) >= max_items:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                key_path = f"{path}.{key}" if path else str(key)
                key_l = str(key).lower()
                if key_l in {"error", "errors", "message", "reason", "detail"} and nested:
                    text = str(nested).strip()
                    if text:
                        found.append(f"{key_path}: {text}")
                elif any(token in key_l for token in ("error", "failed", "failure")) and nested:
                    found.append(f"{key_path}: {nested}")
                walk(nested, key_path)
        elif isinstance(value, list):
            for i, nested in enumerate(value):
                walk(nested, f"{path}[{i}]")
        elif path and isinstance(value, str):
            lowered = value.lower()
            if any(token in lowered for token in ("publishing error", "publish failed", "sync failed", "failed")):
                found.append(f"{path}: {value}")

    walk(payload)
    return found[:max_items]




def _is_transient_publish_error(exc: PrintifyAPIError) -> bool:
    body = (exc.response_body or "").lower()
    return exc.status_code == 429 or "too many" in body or "rate" in body


def _publish_with_backoff(shop_id: str, product_id: str, row: dict[str, str], *, max_attempts: int = 4, spacing_s: float = 0.6) -> dict[str, Any]:
    last_exc: PrintifyAPIError | None = None
    for attempt in range(1, max_attempts + 1):
        row["publish_attempt_count"] = str(attempt)
        try:
            resp = printify_publish(shop_id, product_id)
            row["publish_retry_eligible"] = "NO"
            return resp
        except PrintifyAPIError as exc:
            last_exc = exc
            transient = _is_transient_publish_error(exc)
            row["publish_retry_eligible"] = "YES" if transient else "NO"
            if transient and attempt < max_attempts:
                wait_s = spacing_s * (2 ** (attempt - 1))
                row["error_stage"] = "PUBLISH"
                row["error_message"] = f"Publish throttled (429/transient). Retrying in {wait_s:.1f}s (attempt {attempt}/{max_attempts})."
                row["last_publish_response"] = json.dumps({"status": exc.status_code, "body": exc.response_body, "retry_in_s": wait_s, "attempt": attempt}, ensure_ascii=False)[:5000]
                time.sleep(wait_s)
                continue
            raise
    if last_exc:
        raise last_exc
    return {}

def _extract_shopify_identity_from_printify_product(product: dict[str, Any]) -> tuple[str, str]:
    external = product.get("external") if isinstance(product.get("external"), dict) else {}
    sales_channel = product.get("sales_channel_properties") if isinstance(product.get("sales_channel_properties"), dict) else {}
    external_sc = sales_channel.get("external") if isinstance(sales_channel.get("external"), dict) else {}

    shopify_id = str(
        external.get("id")
        or sales_channel.get("product_id")
        or external_sc.get("id")
        or ""
    ).strip()
    handle = str(
        external.get("handle")
        or sales_channel.get("handle")
        or external_sc.get("handle")
        or ""
    ).strip()
    return shopify_id, handle


def _summarize_sync_payload(product: dict[str, Any], error_details: list[str]) -> dict[str, Any]:
    publish_details = product.get("publishing") if isinstance(product.get("publishing"), dict) else {}
    sales_channel = product.get("sales_channel_properties") if isinstance(product.get("sales_channel_properties"), dict) else {}
    return {
        "id": product.get("id"),
        "visible": product.get("visible"),
        "is_locked": product.get("is_locked"),
        "external": product.get("external") if isinstance(product.get("external"), dict) else {},
        "sales_channel_properties": sales_channel,
        "publishing": publish_details,
        "error_details": error_details,
    }

def _sync_status_check(row: dict[str, str], shop_id: str) -> None:
    row["last_sync_check_at"] = now_iso()
    if not row.get("printify_product_id"):
        row["shopify_sync_status"] = "NOT_ATTEMPTED"
        return

    product: dict[str, Any] = {}
    error_details: list[str] = []
    try:
        product = get_product(shop_id, row["printify_product_id"])
        error_details = _collect_error_strings(product)
    except Exception as exc:
        row["shopify_sync_status"] = "NOT_ATTEMPTED"
        row["last_sync_response"] = json.dumps({"error": f"Printify product lookup failed: {exc}"}, ensure_ascii=False)[:5000]
        return

    printify_shopify_id, printify_handle = _extract_shopify_identity_from_printify_product(product)
    if printify_handle:
        row["shopify_handle"] = printify_handle

    shopify_id = row.get("shopify_product_id") or printify_shopify_id or ""
    if not shopify_id and row.get("shopify_handle"):
        found = find_product_by_handle(row.get("shopify_handle", ""))
        shopify_id = str(found.get("id", ""))
        if found.get("handle"):
            row["shopify_handle"] = str(found["handle"])
    if not shopify_id:
        shopify_id = find_product_id_by_title(row.get("title", ""))
    if shopify_id:
        row["shopify_product_id"] = shopify_id
        row["shopify_sync_status"] = "SYNCED_TO_SHOPIFY"
        row["error_stage"] = "" if row.get("error_stage") == "SHOPIFY_SYNC" else row.get("error_stage", "")
        row["error_message"] = "" if row.get("error_stage") == "SHOPIFY_SYNC" else row.get("error_message", "")
        row["printify_publish_error"] = ""
    elif error_details:
        row["shopify_sync_status"] = "SYNC_FAILED"
        row["error_stage"] = "SHOPIFY_SYNC"
        row["error_message"] = "; ".join(error_details)[:1000]
        row["printify_publish_error"] = row["error_message"]
    else:
        row["shopify_sync_status"] = "SYNC_PENDING"
        if row.get("error_stage") == "SHOPIFY_SYNC":
            row["error_stage"] = ""
            row["error_message"] = ""
            row["printify_publish_error"] = ""

    row["last_sync_response"] = json.dumps(_summarize_sync_payload(product, error_details), ensure_ascii=False)[:5000]



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
    if row.get("profile_resolved") == "NO" or row.get("launch_status") == "BLOCKED_PROFILE":
        row["error_stage"] = "PROFILE"
        row["launch_status"] = "BLOCKED_PROFILE"
        row["status"] = "BLOCKED_PROFILE"
        row["error_message"] = row.get("error_message") or "Unresolved profile metadata: blueprint/provider/variant IDs missing. Run Printify profile resolver."
        row["printify_publish_status"] = "BLOCKED_PROFILE"
        row["shopify_sync_status"] = "BLOCKED_PROFILE"
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
        existing_product_id = (row.get("printify_product_id") or "").strip()
        if existing_product_id:
            row["printify_product_id"] = existing_product_id
            row["last_publish_response"] = json.dumps({"reused_printify_product_id": existing_product_id}, ensure_ascii=False)[:5000]
        else:
            created = create_product(shop_id, payload)
            row["printify_product_id"] = str(created.get("id", ""))
            row["last_publish_response"] = json.dumps(created, ensure_ascii=False)[:5000]
        row["printify_publish_status"] = "PUBLISHED_TO_PRINTIFY" if row["printify_product_id"] else "PUBLISH_FAILED"
        if row.get("publish_mode") in ("personalized", "both"):
            row["needs_manual_personalization_setup"] = "YES"
        if row["printify_product_id"]:
            time.sleep(0.45)
            publish_resp = _publish_with_backoff(shop_id, row["printify_product_id"], row)
            row["last_publish_response"] = json.dumps(publish_resp, ensure_ascii=False)[:5000]
            row["printify_publish_status"] = "PUBLISHED_TO_PRINTIFY"
            _sync_status_check(row, shop_id)
            row["status"] = "PUBLISHED_TO_PRINTIFY"
            row["launch_status"] = "PUBLISHED_TO_PRINTIFY"
            row["error_stage"] = ""
            row["error_message"] = ""
            row["publish_retry_eligible"] = "NO"
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
        row["publish_retry_eligible"] = "YES" if _is_transient_publish_error(exc) else "NO"
        _set_publish_failure(row, stage="PRINTIFY_API", message=str(exc), response=response)
    except Exception as exc:
        response = {"error": str(exc), "payload_summary": payload_summary}
        row["publish_retry_eligible"] = "NO"
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
