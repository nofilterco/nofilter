from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from catalog_assets import style_variant_for_listing

QUEUE_PATH = Path("queue.csv")

NEW_SCHEMA = [
    "id","status","pipeline_stage","store_brand","collection_slug","collection_title","shopify_collection_tag","listing_slug","listing_title","listing_template_id","template_family","product_profile_id","product_family","publish_mode","personalization_mode","personalization_fields_json","text_fields_json","image_upload_fields_json","logo_upload_fields_json","buyer_personalization_schema_json","internal_workflow_metadata_json","personalization_instructions","title","seo_title","description_html","tags_csv","shopify_tags_csv","shopify_product_type","placeholder_art_mode","placeholder_art_text","printify_blueprint_id","printify_provider_id","variant_strategy","show_all_variants","in_stock_only","enabled_variant_ids_json","enabled_sizes_json","enabled_colors_json","price_cents","asset_local_path","asset_r2_url","mockup_local_path","mockup_r2_url","printify_image_id","printify_product_id","shopify_product_id","shopify_handle","shopify_sales_channel_collections","approved_at","published_at","error_stage","error_message","debug_trace","needs_manual_personalization_setup","printify_publish_status","shopify_sync_status","launch_status","last_publish_response","last_sync_response","last_sync_check_at","printify_publish_error","publish_log_history_json",
    "preview_style","style_variant","preview_artifacts_json","manual_setup_packet_path","manual_setup_packet_json","manual_setup_status","featured_flag","merchandising_priority",
    "profile_resolved","blueprint_id","provider_id","matched_variant_count","enabled_variant_count_before_filter","enabled_variant_count_after_filter","customer_editable_summary",
    "customizable_badge_text","personalization_cta","editable_fields_summary","supports_photo_upload","supports_logo_upload","supports_text_edit",
    "storefront_personalization_headline","storefront_personalization_subtext","storefront_badges",
    "personalization_hub_ready","requires_shopify_republish_for_personalization","printify_personalize_button_required",
    "variant_visibility_mode","shipping_mode","shipping_profile_strategy","shipping_profile_name","sync_detail_defaults_json","collections_sync_mode",
    "variant_visibility_recommended","shipping_profile_recommended","shipping_mode_recommended","sync_details_recommended","collections_recommended",
    "should_enable_personalization","personalization_toggle_manual_required","personalize_button_theme_block_required","requires_new_listing_for_personalization_if_already_published",
    "publish_retry_eligible","publish_attempt_count"
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_if_needed() -> None:
    if not QUEUE_PATH.exists():
        _write([])
        return
    with QUEUE_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = reader.fieldnames or []
    if set(NEW_SCHEMA).issubset(set(headers)):
        return
    backup = QUEUE_PATH.with_name(f"queue.backup.{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
    backup.write_text(QUEUE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    migrated: list[dict[str, str]] = []
    for i, row in enumerate(rows, start=1):
        n = {k: (row.get(k, "") if isinstance(row, dict) else "") for k in NEW_SCHEMA}
        n["id"] = row.get("id") or str(i)
        n["status"] = row.get("status") or "DRAFT"
        n["pipeline_stage"] = row.get("pipeline_stage") or "LEGACY_IMPORTED"
        n["store_brand"] = row.get("store_brand") or "Crafted Occasion"
        n["listing_title"] = row.get("listing_title") or row.get("title") or f"Legacy Row {i}"
        n["title"] = row.get("title") or n["listing_title"]
        n["description_html"] = row.get("description") or row.get("description_html") or ""
        n["tags_csv"] = row.get("tags") or row.get("tags_csv") or ""
        n["debug_trace"] = row.get("debug_trace") or "legacy-row-imported"
        n["show_all_variants"] = row.get("show_all_variants") or "NO"
        n["in_stock_only"] = row.get("in_stock_only") or "YES"
        n["printify_publish_status"] = row.get("printify_publish_status") or "NOT_ATTEMPTED"
        n["shopify_sync_status"] = row.get("shopify_sync_status") or "NOT_ATTEMPTED"
        n["launch_status"] = row.get("launch_status") or "NOT_ATTEMPTED"
        n["publish_log_history_json"] = row.get("publish_log_history_json") or "[]"
        n["preview_artifacts_json"] = row.get("preview_artifacts_json") or "{}"
        n["manual_setup_status"] = row.get("manual_setup_status") or "not_required"
        n["style_variant"] = row.get("style_variant") or ""
        n["customer_editable_summary"] = row.get("customer_editable_summary") or ""
        n["publish_retry_eligible"] = row.get("publish_retry_eligible") or "NO"
        n["publish_attempt_count"] = row.get("publish_attempt_count") or "0"
        n["variant_visibility_mode"] = row.get("variant_visibility_mode") or ("in_stock_only" if (n.get("in_stock_only") == "YES") else "show_all_variants")
        n["shipping_mode"] = row.get("shipping_mode") or "standard_only"
        n["shipping_profile_strategy"] = row.get("shipping_profile_strategy") or "use_store_default"
        n["shipping_profile_name"] = row.get("shipping_profile_name") or ""
        n["sync_detail_defaults_json"] = row.get("sync_detail_defaults_json") or "[\"product_title\", \"description\", \"mockups\", \"colors_sizes_prices_skus\", \"tags\", \"shipping_profile\"]"
        n["collections_sync_mode"] = row.get("collections_sync_mode") or "apply_launch_collections"
        n["variant_visibility_recommended"] = row.get("variant_visibility_recommended") or n["variant_visibility_mode"]
        n["shipping_profile_recommended"] = row.get("shipping_profile_recommended") or n["shipping_profile_strategy"]
        n["shipping_mode_recommended"] = row.get("shipping_mode_recommended") or n["shipping_mode"]
        n["sync_details_recommended"] = row.get("sync_details_recommended") or n["sync_detail_defaults_json"]
        n["collections_recommended"] = row.get("collections_recommended") or (row.get("shopify_sales_channel_collections") or row.get("collection_title") or "")
        n["should_enable_personalization"] = row.get("should_enable_personalization") or ("YES" if (row.get("publish_mode") in {"personalized", "both"}) else "NO")
        n["personalization_toggle_manual_required"] = row.get("personalization_toggle_manual_required") or n.get("needs_manual_personalization_setup") or "NO"
        n["personalize_button_theme_block_required"] = row.get("personalize_button_theme_block_required") or n.get("printify_personalize_button_required") or "NO"
        n["requires_new_listing_for_personalization_if_already_published"] = row.get("requires_new_listing_for_personalization_if_already_published") or n.get("requires_shopify_republish_for_personalization") or "NO"
        migrated.append(n)
    _write(migrated)


def _write(rows: list[dict[str, Any]]) -> None:
    with QUEUE_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=NEW_SCHEMA)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in NEW_SCHEMA})


def _safe_json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _derive_storefront_personalization(row: dict[str, str]) -> dict[str, str]:
    text_fields = _safe_json_list(row.get("text_fields_json") or row.get("personalization_fields_json") or "[]")
    image_fields = _safe_json_list(row.get("image_upload_fields_json") or "[]")
    logo_fields = _safe_json_list(row.get("logo_upload_fields_json") or "[]")
    summary = row.get("customer_editable_summary") or f"Text: {len(text_fields)} fields | Image uploads: {len(image_fields)} | Logo uploads: {len(logo_fields)}"

    badges: list[str] = []
    if text_fields:
        badges.append("Custom Text")
    if image_fields:
        badges.append("Photo Upload")
    if logo_fields:
        badges.append("Logo Upload")

    has_personalization = bool(text_fields or image_fields or logo_fields)
    supports_any = any([
        (row.get("supports_text_edit") or ("YES" if text_fields else "NO")) == "YES",
        (row.get("supports_photo_upload") or ("YES" if image_fields else "NO")) == "YES",
        (row.get("supports_logo_upload") or ("YES" if logo_fields else "NO")) == "YES",
    ])
    is_synced = (row.get("shopify_sync_status") or "") == "SYNCED_TO_SHOPIFY" and bool(row.get("shopify_product_id"))
    packet_ready = row.get("manual_setup_status") == "generated" and bool(row.get("manual_setup_packet_path"))
    needs_manual = row.get("needs_manual_personalization_setup", "NO") == "YES"

    requires_republish = "YES" if (is_synced and supports_any and needs_manual) else "NO"
    personalize_button_required = "YES" if (has_personalization or supports_any) else "NO"
    personalization_hub_ready = "YES" if (supports_any and is_synced and packet_ready and not needs_manual) else "NO"

    return {
        "customer_editable_summary": summary,
        "editable_fields_summary": row.get("editable_fields_summary") or summary,
        "supports_text_edit": row.get("supports_text_edit") or ("YES" if text_fields else "NO"),
        "supports_photo_upload": row.get("supports_photo_upload") or ("YES" if image_fields else "NO"),
        "supports_logo_upload": row.get("supports_logo_upload") or ("YES" if logo_fields else "NO"),
        "customizable_badge_text": row.get("customizable_badge_text") or ("Personalizable" if badges else "Ready to Order"),
        "personalization_cta": row.get("personalization_cta") or ("Customize with your details" if badges else "Choose your options"),
        "storefront_personalization_headline": row.get("storefront_personalization_headline") or ("Make it yours" if badges else "Made for gifting"),
        "storefront_personalization_subtext": row.get("storefront_personalization_subtext") or (
            "Add your name, date, photo, or logo before checkout" if badges else "Thoughtful design for special moments"
        ),
        "storefront_badges": row.get("storefront_badges") or ", ".join(badges),
        "personalization_hub_ready": row.get("personalization_hub_ready") or personalization_hub_ready,
        "requires_shopify_republish_for_personalization": row.get("requires_shopify_republish_for_personalization") or requires_republish,
        "printify_personalize_button_required": row.get("printify_personalize_button_required") or personalize_button_required,
    }



def _derive_publish_defaults(row: dict[str, str]) -> dict[str, str]:
    sync_defaults = row.get("sync_detail_defaults_json") or ""
    if not sync_defaults or sync_defaults == "[]":
        sync_defaults = '["product_title", "description", "mockups", "colors_sizes_prices_skus", "tags", "shipping_profile"]'
    collections = row.get("shopify_sales_channel_collections") or row.get("collection_title") or ""
    return {
        "variant_visibility_mode": row.get("variant_visibility_mode") or ("in_stock_only" if (row.get("in_stock_only") == "YES") else "show_all_variants"),
        "shipping_mode": row.get("shipping_mode") or "standard_only",
        "shipping_profile_strategy": row.get("shipping_profile_strategy") or "use_store_default",
        "shipping_profile_name": row.get("shipping_profile_name") or "",
        "sync_detail_defaults_json": sync_defaults,
        "collections_sync_mode": row.get("collections_sync_mode") or "apply_launch_collections",
        "variant_visibility_recommended": row.get("variant_visibility_recommended") or (row.get("variant_visibility_mode") or ("in_stock_only" if (row.get("in_stock_only") == "YES") else "show_all_variants")),
        "shipping_profile_recommended": row.get("shipping_profile_recommended") or (row.get("shipping_profile_strategy") or "use_store_default"),
        "shipping_mode_recommended": row.get("shipping_mode_recommended") or (row.get("shipping_mode") or "standard_only"),
        "sync_details_recommended": row.get("sync_details_recommended") or sync_defaults,
        "collections_recommended": row.get("collections_recommended") or collections,
        "should_enable_personalization": row.get("should_enable_personalization") or ("YES" if (row.get("publish_mode") in {"personalized", "both"}) else "NO"),
        "personalization_toggle_manual_required": row.get("personalization_toggle_manual_required") or row.get("needs_manual_personalization_setup", "NO"),
        "personalize_button_theme_block_required": row.get("personalize_button_theme_block_required") or row.get("printify_personalize_button_required", "NO"),
        "requires_new_listing_for_personalization_if_already_published": row.get("requires_new_listing_for_personalization_if_already_published") or row.get("requires_shopify_republish_for_personalization", "NO"),
    }

def load_rows() -> list[dict[str, str]]:
    migrate_if_needed()
    with QUEUE_PATH.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list[dict[str, Any]]) -> None:
    _write(rows)


def append_rows(new_rows: list[dict[str, Any]]) -> None:
    rows = load_rows()
    rows.extend(new_rows)
    save_rows(rows)


def next_id(rows: list[dict[str, Any]]) -> int:
    vals = []
    for r in rows:
        try:
            vals.append(int(r.get("id") or "0"))
        except Exception:
            pass
    return max(vals or [0]) + 1



def _is_valid_operational_row(row: dict[str, str]) -> bool:
    required = ["collection_slug", "product_profile_id", "template_family", "title", "seo_title", "listing_slug"]
    if any(not (row.get(k) or "").strip() for k in required):
        return False
    preview = json.loads(row.get("preview_artifacts_json") or "{}")
    primary = str(preview.get("primary_preview") or "")
    if "placeholder__primary.png" in primary and not row.get("collection_slug"):
        return False
    return True


def _operational_rows(debug_include_invalid: bool = False) -> list[dict[str, str]]:
    rows = load_rows()
    if debug_include_invalid:
        return rows
    return [r for r in rows if _is_valid_operational_row(r)]



def _clean_seo_title(value: str) -> str:
    words = (value or "").split()
    deduped: list[str] = []
    for token in words:
        key = token.lower()
        if deduped and deduped[-1].lower() == key:
            continue
        deduped.append(token)
    phrase = " ".join(deduped)
    phrase = phrase.replace("Family Reunion Family Reunion", "Family Reunion")
    return phrase


def _clean_public_tags(value: str) -> str:
    blocked = {"reunion_location"}
    tags = [t.strip() for t in (value or "").split(",") if t.strip()]
    tags = [t for t in tags if t.lower() not in blocked]
    return ",".join(dict.fromkeys(tags))

def dump_launch_report(path: str = "launch_report.json", *, debug_include_invalid: bool = False) -> str:
    rows = _operational_rows(debug_include_invalid)
    payload = [{
        "collection": r["collection_slug"], "title": r["title"], "seo_title": _clean_seo_title(r["seo_title"]), "description_html": r["description_html"], "tags": _clean_public_tags(r["tags_csv"]),
        "sizes": json.loads(r["enabled_sizes_json"] or "[]"), "colors": json.loads(r["enabled_colors_json"] or "[]"),
        "profile": r["product_profile_id"], "status": r["status"], "stock_mode": "in_stock_only" if (r.get("in_stock_only") == "YES") else "all_variants",
        "template_family": r.get("template_family", ""),
        "art_strategy_internal": r.get("placeholder_art_mode", ""),
        "launch_status": r.get("launch_status", ""),
        "preview_style": r.get("preview_style", ""),
        "storefront_preview_style": r.get("preview_style", ""),
        "style_variant": r.get("style_variant") or style_variant_for_listing(r.get("listing_slug", ""), r.get("template_family", "")),
        "preview_artifact_paths": json.loads(r.get("preview_artifacts_json") or "{}"),
        "manual_setup_packet_status": r.get("manual_setup_status", ""),
        "manual_setup_packet_path": r.get("manual_setup_packet_path", ""),
        "sync_closure_status": r.get("shopify_sync_status", ""),
        "featured_flag": r.get("featured_flag", "NO"),
        "merchandising_priority": r.get("merchandising_priority", ""),
        "personalization_capability_summary": {
            "template_family": r.get("template_family", ""),
            "text": bool(json.loads(r.get("text_fields_json") or "[]")),
            "image": bool(json.loads(r.get("image_upload_fields_json") or "[]")),
            "logo": bool(json.loads(r.get("logo_upload_fields_json") or "[]")),
        },
        "printify_publish_status": r.get("printify_publish_status", ""),
        "shopify_sync_status": r.get("shopify_sync_status", ""),
        "manual_setup_required": r.get("needs_manual_personalization_setup", "NO"),
        **_derive_storefront_personalization(r),
        **_derive_publish_defaults(r),
        "publish_retry_eligible": r.get("publish_retry_eligible", ""),
        "publish_attempt_count": r.get("publish_attempt_count", ""),
        "printify_product_id": r["printify_product_id"], "shopify_product_id": r["shopify_product_id"],
        "error_stage": r.get("error_stage", ""), "error_message": r.get("error_message", ""),
        "printify_publish_error": r.get("printify_publish_error", ""),
        "last_publish_response": r.get("last_publish_response", ""), "last_sync_response": r.get("last_sync_response", ""),
        "profile_resolved": r.get("profile_resolved", ""), "blueprint_id": r.get("blueprint_id", r.get("printify_blueprint_id", "")), "provider_id": r.get("provider_id", r.get("printify_provider_id", "")),
        "matched_variant_count": r.get("matched_variant_count", "0"), "enabled_variant_count_before_filter": r.get("enabled_variant_count_before_filter", "0"), "enabled_variant_count_after_filter": r.get("enabled_variant_count_after_filter", "0"),
    } for r in rows]
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def dump_ops_review_csv(path: str = "launch_ops_review.csv", *, debug_include_invalid: bool = False) -> str:
    rows = _operational_rows(debug_include_invalid)
    fieldnames = ["id", "collection_slug", "product_family", "template_family", "art_strategy_internal", "preview_style", "style_variant", "storefront_preview_style", "preview_artifacts_json", "title", "status", "launch_status", "printify_publish_status", "shopify_sync_status", "printify_product_id", "shopify_product_id", "needs_manual_personalization_setup", "manual_setup_status", "manual_setup_packet_path", "customer_editable_summary", "customizable_badge_text", "personalization_cta", "editable_fields_summary", "supports_photo_upload", "supports_logo_upload", "supports_text_edit", "storefront_personalization_headline", "storefront_personalization_subtext", "storefront_badges", "personalization_hub_ready", "requires_shopify_republish_for_personalization", "printify_personalize_button_required", "variant_visibility_recommended", "shipping_profile_recommended", "shipping_mode_recommended", "sync_details_recommended", "collections_recommended", "should_enable_personalization", "personalization_toggle_manual_required", "personalize_button_theme_block_required", "requires_new_listing_for_personalization_if_already_published", "publish_retry_eligible", "publish_attempt_count", "featured_flag", "merchandising_priority", "stock_mode", "in_stock_only", "show_all_variants", "enabled_sizes_json", "enabled_colors_json", "profile_resolved", "blueprint_id", "provider_id", "matched_variant_count", "enabled_variant_count_before_filter", "enabled_variant_count_after_filter", "error_stage", "error_message", "printify_publish_error", "last_publish_response", "last_sync_response"]
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            enriched = dict(r)
            enriched["art_strategy_internal"] = r.get("placeholder_art_mode", "")
            enriched["preview_style"] = r.get("preview_style", "")
            enriched["storefront_preview_style"] = r.get("preview_style", "")
            enriched["style_variant"] = r.get("style_variant") or style_variant_for_listing(r.get("listing_slug", ""), r.get("template_family", ""))
            enriched["stock_mode"] = "in_stock_only" if (r.get("in_stock_only") == "YES") else "all_variants"
            enriched.update(_derive_storefront_personalization(r))
            enriched.update(_derive_publish_defaults(r))
            w.writerow({k: enriched.get(k, "") for k in fieldnames})
    return path


def dump_manual_setup_only_csv(path: str = "manual_setup_required.csv") -> str:
    rows = [r for r in load_rows() if r.get("needs_manual_personalization_setup") == "YES"]
    fieldnames = ["id", "listing_slug", "title", "product_family", "status", "launch_status", "manual_setup_status", "manual_setup_packet_path", "customizable_badge_text", "personalization_cta", "editable_fields_summary", "supports_photo_upload", "supports_logo_upload", "supports_text_edit", "storefront_personalization_headline", "storefront_personalization_subtext", "storefront_badges"]
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            enriched = dict(r)
            enriched["art_strategy_internal"] = r.get("placeholder_art_mode", "")
            enriched["preview_style"] = r.get("preview_style", "")
            enriched["storefront_preview_style"] = r.get("preview_style", "")
            enriched["style_variant"] = r.get("style_variant") or style_variant_for_listing(r.get("listing_slug", ""), r.get("template_family", ""))
            enriched.update(_derive_storefront_personalization(r))
            enriched.update(_derive_publish_defaults(r))
            w.writerow({k: enriched.get(k, "") for k in fieldnames})
    return path


def dump_storefront_personalization_checklist_csv(path: str = "shopify_personalization_setup_checklist.csv") -> str:
    rows = [r for r in _operational_rows() if (r.get("shopify_product_id") or "").strip()]
    fieldnames = [
        "id", "title", "listing_slug", "shopify_product_id", "printify_product_id", "template_family", "style_variant",
        "customer_editable_summary", "editable_fields_summary", "supports_text_edit", "supports_photo_upload", "supports_logo_upload",
        "personalization_hub_ready", "requires_shopify_republish_for_personalization", "printify_personalize_button_required",
        "variant_visibility_recommended", "shipping_profile_recommended", "shipping_mode_recommended", "sync_details_recommended", "collections_recommended",
        "should_enable_personalization", "personalization_toggle_manual_required", "personalize_button_theme_block_required", "requires_new_listing_for_personalization_if_already_published",
        "manual_setup_status", "manual_setup_packet_path", "storefront_personalization_headline", "storefront_personalization_subtext",
        "storefront_badges", "preview_artifacts_json", "storefront_setup_reminder",
    ]
    reminder = "Add/verify the Printify Personalize Button app block on Shopify product template and test storefront customization visibility."
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            enriched = dict(r)
            enriched["style_variant"] = r.get("style_variant") or style_variant_for_listing(r.get("listing_slug", ""), r.get("template_family", ""))
            enriched.update(_derive_storefront_personalization(r))
            enriched.update(_derive_publish_defaults(r))
            enriched["storefront_setup_reminder"] = reminder
            w.writerow({k: enriched.get(k, "") for k in fieldnames})
    return path
