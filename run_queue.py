from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from catalog_assets import build_placeholder_asset, build_storefront_preview_set, default_placeholder_text, resolve_art_strategy
from catalog_builders import build_description_html, build_seo_title, build_tags_csv, build_title
from catalog_config import catalog_indexes, load_catalog
from catalog_queue import append_rows, dump_launch_report, dump_manual_setup_only_csv, dump_ops_review_csv, load_rows, next_id, save_rows
from publish_product import publish_listing, recheck_sync_for_row, resolve_profile, resolve_variants
from setup_packet import generate_setup_packet

REVIEW_FLOW = ["DRAFT", "READY_FOR_REVIEW", "APPROVED", "REJECTED", "BLOCKED_PROFILE", "PUBLISHED_TO_PRINTIFY", "SYNC_PENDING", "SYNCED_TO_SHOPIFY", "MANUAL_PERSONALIZATION_REQUIRED", "PUBLISH_FAILED", "SYNC_FAILED"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_publish_log(row: dict[str, Any], event: str, detail: str = "") -> None:
    logs = json.loads(row.get("publish_log_history_json") or "[]")
    logs.append({"ts": now_iso(), "event": event, "detail": detail[:500]})
    row["publish_log_history_json"] = json.dumps(logs[-30:])


def _buyer_schema_for_listing(item: dict[str, Any], tpl: dict[str, Any], placeholder_text: str) -> dict[str, Any]:
    text_fields = item.get("personalization_fields") or tpl.get("personalization_fields") or []
    return {
        "text_fields": text_fields,
        "image_fields": item.get("image_upload_fields") or tpl.get("image_upload_fields") or [],
        "logo_fields": item.get("logo_upload_fields") or tpl.get("logo_upload_fields") or [],
        "helper_text": tpl.get("personalization_instructions", ""),
        "placeholder_preview": placeholder_text,
    }


def _apply_merch(row: dict[str, Any], coll: dict[str, Any]) -> None:
    featured = set(coll.get("featured_listing_slugs", []))
    row["featured_flag"] = "YES" if row.get("listing_slug") in featured else "NO"
    row["merchandising_priority"] = str(coll.get("sort_priority", 100))


def seed_listings(from_launch_plan: bool = True, collection: str = "", family: str = "") -> int:
    catalog = load_catalog()
    idx = catalog_indexes(catalog)
    source = catalog["launch_plan"] if from_launch_plan else catalog["listing_templates"]
    rows = load_rows()
    existing = {r.get("listing_slug") for r in rows}
    start = next_id(rows)
    out: list[dict[str, Any]] = []
    base_keys = list(rows[0].keys()) if rows else []
    for item in source:
        profile = idx["profiles"].get(item.get("product_profile_id"), {})
        coll_slug = item.get("collection_slug", "")
        if collection and coll_slug != collection:
            continue
        if family and profile.get("product_family") != family:
            continue
        slug = item.get("listing_slug") or item.get("slug")
        if slug in existing:
            continue
        coll = idx["collections"][coll_slug]
        tpl = idx["templates"].get(item.get("listing_template_id", ""), {})
        row = {k: "" for k in base_keys}
        pf = profile.get("product_family", "")
        strategy = resolve_art_strategy(item.get("template_family", tpl.get("template_family", "text_only")), slug, pf)
        preview_text = default_placeholder_text(slug, item.get("template_family", tpl.get("template_family", "text_only")))
        row.update({
            "id": str(start + len(out)), "status": "DRAFT", "pipeline_stage": "SEEDED", "store_brand": "Crafted Occasion",
            "collection_slug": coll_slug, "collection_title": coll["title"], "shopify_collection_tag": coll["shopify_tag"],
            "listing_slug": slug, "listing_title": item.get("exact_title") or item.get("title_template", ""),
            "listing_template_id": item.get("listing_template_id", slug), "template_family": item.get("template_family", tpl.get("template_family", "text_only")),
            "product_profile_id": item.get("product_profile_id", ""), "publish_mode": item.get("publish_mode", "personalized"),
            "personalization_fields_json": json.dumps(item.get("personalization_fields", tpl.get("personalization_fields", []))),
            "image_upload_fields_json": json.dumps(item.get("image_upload_fields", tpl.get("image_upload_fields", []))),
            "logo_upload_fields_json": json.dumps(item.get("logo_upload_fields", tpl.get("logo_upload_fields", []))),
            "text_fields_json": json.dumps(item.get("text_fields", tpl.get("text_fields", []))),
            "buyer_personalization_schema_json": json.dumps(_buyer_schema_for_listing(item, tpl, preview_text)),
            "internal_workflow_metadata_json": json.dumps({**tpl.get("internal_workflow_metadata", {}), "art_strategy": strategy}),
            "personalization_instructions": tpl.get("personalization_instructions", "Manual personalization review may be required."),
            "title": build_title(item, tpl), "seo_title": build_seo_title(item, tpl), "description_html": build_description_html(item, tpl),
            "tags_csv": build_tags_csv(item, coll, tpl, profile), "shopify_tags_csv": coll["shopify_tag"],
            "placeholder_art_mode": strategy, "placeholder_art_text": preview_text,
            "enabled_sizes_json": json.dumps(item.get("launch_visible_sizes", profile.get("launch_visible_sizes", []))),
            "enabled_colors_json": json.dumps(item.get("launch_visible_colors", profile.get("launch_visible_colors", coll.get("default_visible_colors", [])))),
            "price_cents": str(item.get("suggested_retail_price_cents", profile.get("retail_pricing_defaults", {}).get("default_cents", 2499))),
            "variant_strategy": "curated_launch", "show_all_variants": "NO", "in_stock_only": "YES" if pf in {"tee", "hoodie", "crewneck", "mug"} else "NO",
            "printify_publish_status": "not_attempted", "shopify_sync_status": "SYNC_PENDING", "launch_status": "MANUAL_PERSONALIZATION_REQUIRED",
            "publish_log_history_json": json.dumps([{"ts": now_iso(), "event": "SEEDED", "detail": slug}]), "debug_trace": f"{now_iso()}:seeded",
        })
        _apply_merch(row, coll)
        resolve_profile(row, profile)
        if row.get("launch_status") == "BLOCKED_PROFILE":
            row["status"] = "BLOCKED_PROFILE"
        out.append(row)
    append_rows(out)
    return len(out)


def build_assets_for_rows(limit: int = 0) -> int:
    rows = load_rows(); idx = catalog_indexes(load_catalog()); done = 0
    for row in rows:
        if row["status"] not in ("DRAFT", "READY_FOR_REVIEW"):
            continue
        tpl = idx["templates"].get(row.get("listing_template_id", ""), {})
        safe_areas = tpl.get("product_safe_area", {}) if isinstance(tpl.get("product_safe_area", {}), dict) else {}
        row["asset_local_path"] = build_placeholder_asset(row.get("placeholder_art_text") or row["listing_title"], row["listing_slug"], product_family=row.get("product_family", "tee"), art_strategy=row.get("placeholder_art_mode", "stacked_text"), collection_slug=row.get("collection_slug", "family-reunion"), style_pack=tpl.get("style_pack", row.get("collection_slug", "")), contrast_mode=tpl.get("contrast_mode", "auto"), blank_color=(json.loads(row.get("enabled_colors_json") or "[]") or ["White"])[0], product_safe_area=safe_areas.get(row.get("product_family", "tee"), {}))
        preview = build_storefront_preview_set(row)
        row["preview_style"] = preview["preview_style"]
        row["preview_artifacts_json"] = json.dumps(preview)
        row["pipeline_stage"] = "ASSET_BUILT"; row["status"] = "READY_FOR_REVIEW"
        _append_publish_log(row, "ASSET_BUILT", row["asset_local_path"])
        _append_publish_log(row, "PREVIEW_SET", row["preview_style"])
        done += 1
        if limit and done >= limit: break
    save_rows(rows); return done


def mark_review(status: str, ids: list[str] | None = None) -> int:
    rows = load_rows(); updated = 0
    for row in rows:
        if ids and row["id"] not in ids: continue
        if status == "APPROVED" and row["status"] == "READY_FOR_REVIEW":
            row["status"] = "APPROVED"; row["launch_status"] = "APPROVED"; row["approved_at"] = now_iso(); _append_publish_log(row, "APPROVED"); updated += 1
        elif status == "REJECTED" and row["status"] in ("READY_FOR_REVIEW", "APPROVED"):
            row["status"] = "REJECTED"; _append_publish_log(row, "REJECTED"); updated += 1
    save_rows(rows); return updated


def generate_setup_packets(ids: list[str] | None = None) -> int:
    rows = load_rows(); done = 0
    for row in rows:
        if ids and row.get("id") not in ids:
            continue
        if row.get("needs_manual_personalization_setup") != "YES" and row.get("publish_mode") not in {"personalized", "both"}:
            continue
        row["needs_manual_personalization_setup"] = "YES"
        packet = generate_setup_packet(row)
        row["manual_setup_packet_path"] = packet["path"]
        row["manual_setup_packet_json"] = json.dumps(packet["packet"])
        row["manual_setup_status"] = "generated"
        if row.get("status") != "SYNCED_TO_SHOPIFY":
            row["launch_status"] = "MANUAL_PERSONALIZATION_REQUIRED"
        _append_publish_log(row, "SETUP_PACKET_GENERATED", packet["path"])
        done += 1
    save_rows(rows); return done


def recheck_sync(ids: list[str] | None = None) -> int:
    rows = load_rows(); checked = 0
    for row in rows:
        if ids and row["id"] not in ids: continue
        if row.get("launch_status") == "BLOCKED_PROFILE" or row.get("status") == "BLOCKED_PROFILE":
            row["status"] = "BLOCKED_PROFILE"
            row["launch_status"] = "BLOCKED_PROFILE"
            _append_publish_log(row, "SYNC_RECHECK_SKIPPED", "blocked profile")
            checked += 1
            continue
        if row.get("printify_publish_status") not in {"published", "created"}:
            _append_publish_log(row, "SYNC_RECHECK_SKIPPED", "not published to printify")
            checked += 1
            continue
        recheck_sync_for_row(row)
        if row.get("shopify_sync_status") == "SYNCED_TO_SHOPIFY":
            row["launch_status"] = "SYNCED_TO_SHOPIFY"
            row["status"] = "SYNCED_TO_SHOPIFY"
        elif row.get("shopify_sync_status") == "SYNC_FAILED":
            row["launch_status"] = "SYNC_FAILED"; row["status"] = "SYNC_FAILED"
        else:
            row["launch_status"] = "SYNC_PENDING"
            if row.get("status") == "PUBLISHED_TO_PRINTIFY":
                row["status"] = "SYNC_PENDING"
        _append_publish_log(row, "SYNC_RECHECK", row.get("shopify_sync_status", "")); checked += 1
    save_rows(rows); return checked


def export_row_json(row_id: str, out_dir: str = "out") -> str:
    rows = load_rows(); row = next((r for r in rows if r.get("id") == str(row_id)), None)
    if not row: raise ValueError(f"Row id {row_id} not found")
    p = Path(out_dir); p.mkdir(exist_ok=True)
    path = p / f"queue_row_{row_id}.json"; path.write_text(json.dumps(row, indent=2), encoding="utf-8")
    return str(path)


def publish_approved(limit: int = 0, *, dry_run: bool = False, debug_title: str = "") -> int:
    rows = load_rows(); idx = catalog_indexes(load_catalog()); count = 0
    for row in rows:
        if row["status"] != "APPROVED": continue
        profile = idx["profiles"].get(row.get("product_profile_id", ""), {})
        resolve_profile(row, profile); resolve_variants(row, profile)
        try:
            if not json.loads(row.get("enabled_variant_ids_json") or "[]"):
                row["enabled_variant_ids_json"] = "[1]"
            publish_listing(row, dry_run=dry_run)
            if dry_run:
                row["pipeline_stage"] = "PUBLISH_DRY_RUN"
            elif row.get("printify_publish_status") == "published":
                row["published_at"] = now_iso(); row["pipeline_stage"] = "PUBLISHED"; row["status"] = "PUBLISHED_TO_PRINTIFY"; row["launch_status"] = "PUBLISHED_TO_PRINTIFY"
                if row.get("shopify_sync_status") == "SYNCED_TO_SHOPIFY": row["status"] = "SYNCED_TO_SHOPIFY"; row["launch_status"] = "SYNCED_TO_SHOPIFY"
                elif row.get("shopify_sync_status") == "SYNC_PENDING": row["launch_status"] = "SYNC_PENDING"
                elif row.get("shopify_sync_status") == "SYNC_FAILED": row["launch_status"] = "SYNC_FAILED"; row["status"] = "SYNC_FAILED"
                if row.get("needs_manual_personalization_setup") == "YES" and row.get("status") != "SYNCED_TO_SHOPIFY": row["launch_status"] = "MANUAL_PERSONALIZATION_REQUIRED"
            else:
                row["pipeline_stage"] = "PUBLISH_FAILED"; row["status"] = "PUBLISH_FAILED"; row["launch_status"] = "PUBLISH_FAILED"; row["error_stage"] = row.get("error_stage") or "PUBLISH"
                row["error_message"] = row.get("error_message") or "Create product succeeded without printify_product_id"
        except Exception as exc:
            row["pipeline_stage"] = "PUBLISH_FAILED"; row["status"] = "PUBLISH_FAILED"; row["launch_status"] = "PUBLISH_FAILED"; row["error_stage"] = row.get("error_stage") or "PUBLISH"; row["error_message"] = str(exc)
        _append_publish_log(row, "PUBLISH_ATTEMPT", row.get("printify_publish_status", ""))
        count += 1
        if limit and count >= limit: break
    save_rows(rows); return count


def main() -> None:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
    p = argparse.ArgumentParser(description="Crafted Occasion catalog queue runner")
    p.add_argument("--seed-launch", action="store_true"); p.add_argument("--collection", default=""); p.add_argument("--family", default="")
    p.add_argument("--build-assets", action="store_true"); p.add_argument("--approve-all", action="store_true"); p.add_argument("--reject-all", action="store_true")
    p.add_argument("--publish-approved", action="store_true"); p.add_argument("--recheck-sync", action="store_true")
    p.add_argument("--setup-packets", action="store_true"); p.add_argument("--export-manual-setup-only", action="store_true")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--debug-payload-title", default="")
    p.add_argument("--export-report", action="store_true"); args = p.parse_args()
    if args.seed_launch: print(f"seeded={seed_listings(True, args.collection, args.family)}")
    if args.build_assets: print(f"assets={build_assets_for_rows()}")
    if args.approve_all: print(f"approved={mark_review('APPROVED')}")
    if args.reject_all: print(f"rejected={mark_review('REJECTED')}")
    if args.publish_approved: print(f"published={publish_approved(dry_run=args.dry_run, debug_title=args.debug_payload_title)}")
    if args.recheck_sync: print(f"sync_checked={recheck_sync()}")
    if args.setup_packets: print(f"setup_packets={generate_setup_packets()}")
    if args.export_manual_setup_only: print(f"manual_setup_export={dump_manual_setup_only_csv()}")
    if args.export_report: print(f"report={dump_launch_report()} ops_csv={dump_ops_review_csv()}")


if __name__ == "__main__":
    main()
