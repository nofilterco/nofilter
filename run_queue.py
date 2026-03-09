from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from catalog_assets import build_placeholder_asset
from catalog_builders import build_description_html, build_seo_title, build_tags_csv, build_title
from catalog_config import catalog_indexes, load_catalog
from catalog_queue import append_rows, dump_launch_report, load_rows, next_id, save_rows
from publish_product import publish_listing, resolve_profile, resolve_variants

REVIEW_FLOW = ["DRAFT", "READY_FOR_REVIEW", "APPROVED", "REJECTED", "PUBLISHED"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_listings(from_launch_plan: bool = True, collection: str = "", family: str = "") -> int:
    catalog = load_catalog()
    idx = catalog_indexes(catalog)
    source = catalog["launch_plan"] if from_launch_plan else catalog["listing_templates"]
    rows = load_rows()
    existing = {r.get("listing_slug") for r in rows}
    start = next_id(rows)
    out: list[dict[str, Any]] = []
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
        row = {k: "" for k in load_rows()[0].keys()} if rows else {}
        pf = profile.get("product_family", "")
        default_in_stock_only = pf in {"tee", "hoodie", "crewneck", "mug"}
        default_show_all_variants = False
        row.update({
            "id": str(start + len(out)),
            "status": "DRAFT",
            "pipeline_stage": "SEEDED",
            "store_brand": "Crafted Occasion",
            "collection_slug": coll_slug,
            "collection_title": coll["title"],
            "shopify_collection_tag": coll["shopify_tag"],
            "listing_slug": slug,
            "listing_title": item.get("exact_title") or item.get("title_template", ""),
            "listing_template_id": item.get("listing_template_id", slug),
            "product_profile_id": item.get("product_profile_id", ""),
            "publish_mode": item.get("publish_mode", "personalized"),
            "personalization_fields_json": json.dumps(item.get("personalization_fields", tpl.get("personalization_fields", []))),
            "image_upload_fields_json": json.dumps(item.get("image_upload_fields", tpl.get("image_upload_fields", []))),
            "logo_upload_fields_json": json.dumps(item.get("logo_upload_fields", tpl.get("logo_upload_fields", []))),
            "text_fields_json": json.dumps(item.get("text_fields", tpl.get("text_fields", []))),
            "personalization_instructions": tpl.get("personalization_instructions", "Manual personalization review may be required."),
            "title": build_title(item, tpl),
            "seo_title": build_seo_title(item, tpl),
            "description_html": build_description_html(item, tpl),
            "tags_csv": build_tags_csv(item, coll, tpl, profile),
            "shopify_tags_csv": coll["shopify_tag"],
            "placeholder_art_mode": tpl.get("art_strategy", "stacked_text"),
            "placeholder_art_text": tpl.get("default_art_placeholder_text", "Custom Text"),
            "enabled_sizes_json": json.dumps(item.get("launch_visible_sizes", profile.get("launch_visible_sizes", []))),
            "enabled_colors_json": json.dumps(item.get("launch_visible_colors", profile.get("launch_visible_colors", []))),
            "price_cents": str(item.get("suggested_retail_price_cents", profile.get("retail_pricing_defaults", {}).get("default_cents", 2499))),
            "variant_strategy": "curated_launch",
            "show_all_variants": "YES" if bool(item.get("show_all_variants", default_show_all_variants)) else "NO",
            "in_stock_only": "YES" if bool(item.get("in_stock_only", default_in_stock_only)) else "NO",
            "printify_publish_status": "not_attempted",
            "shopify_sync_status": "not_checked",
            "debug_trace": f"{now_iso()}:seeded",
        })
        resolve_profile(row, profile)
        out.append(row)
    append_rows(out)
    return len(out)


def build_assets_for_rows(limit: int = 0) -> int:
    rows = load_rows()
    idx = catalog_indexes(load_catalog())
    done = 0
    for row in rows:
        if row["status"] not in ("DRAFT", "READY_FOR_REVIEW"):
            continue
        tpl = idx["templates"].get(row.get("listing_template_id", ""), {})
        safe_areas = tpl.get("product_safe_area", {}) if isinstance(tpl.get("product_safe_area", {}), dict) else {}
        row["asset_local_path"] = build_placeholder_asset(
            row.get("placeholder_art_text") or row["listing_title"],
            row["listing_slug"],
            product_family=row.get("product_family", "tee"),
            art_strategy=row.get("placeholder_art_mode", "stacked_text"),
            collection_slug=row.get("collection_slug", "family-reunion"),
            style_pack=tpl.get("style_pack", row.get("collection_slug", "")),
            contrast_mode=tpl.get("contrast_mode", "auto"),
            blank_color=(json.loads(row.get("enabled_colors_json") or "[]") or ["White"])[0],
            product_safe_area=safe_areas.get(row.get("product_family", "tee"), {}),
        )
        row["pipeline_stage"] = "ASSET_BUILT"
        row["status"] = "READY_FOR_REVIEW"
        row["debug_trace"] = f"{row.get('debug_trace','')} | {now_iso()}:asset_built"
        done += 1
        if limit and done >= limit:
            break
    save_rows(rows)
    return done


def mark_review(status: str, ids: list[str] | None = None) -> int:
    rows = load_rows()
    updated = 0
    for row in rows:
        if ids and row["id"] not in ids:
            continue
        if status == "APPROVED" and row["status"] == "READY_FOR_REVIEW":
            row["status"] = "APPROVED"
            row["approved_at"] = now_iso()
            updated += 1
        elif status == "REJECTED" and row["status"] in ("READY_FOR_REVIEW", "APPROVED"):
            row["status"] = "REJECTED"
            updated += 1
    save_rows(rows)
    return updated


def publish_approved(limit: int = 0, *, dry_run: bool = False, debug_title: str = "") -> int:
    rows = load_rows()
    idx = catalog_indexes(load_catalog())
    count = 0
    for row in rows:
        if row["status"] != "APPROVED":
            continue
        profile = idx["profiles"].get(row.get("product_profile_id", ""), {})
        resolve_profile(row, profile)
        resolve_variants(row, profile)
        try:
            if not json.loads(row.get("enabled_variant_ids_json") or "[]"):
                raise RuntimeError(row.get("error_message") or "No enabled variant ids resolved")
            publish_listing(row, dry_run=dry_run)
            if debug_title and row.get("title") == debug_title:
                print(f"DEBUG_PAYLOAD[{debug_title}]={row.get('_last_printify_payload', '{}')}")
            if dry_run:
                row["pipeline_stage"] = "PUBLISH_DRY_RUN"
            elif row.get("status") == "PUBLISHED" and row.get("printify_product_id"):
                row["published_at"] = now_iso()
                row["pipeline_stage"] = "PUBLISHED"
            else:
                row["pipeline_stage"] = "PUBLISH_FAILED"
                row["status"] = "PUBLISH_FAILED"
                row["error_stage"] = row.get("error_stage") or "PUBLISH"
                row["error_message"] = row.get("error_message") or "Create product succeeded without printify_product_id"
        except Exception as exc:
            row["pipeline_stage"] = "PUBLISH_FAILED"
            row["status"] = "PUBLISH_FAILED"
            row["error_stage"] = row.get("error_stage") or "PUBLISH"
            row["error_message"] = str(exc)
        count += 1
        if limit and count >= limit:
            break
    save_rows(rows)
    return count


def main() -> None:
    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
    p = argparse.ArgumentParser(description="Crafted Occasion catalog queue runner")
    p.add_argument("--seed-launch", action="store_true")
    p.add_argument("--collection", default="")
    p.add_argument("--family", default="")
    p.add_argument("--build-assets", action="store_true")
    p.add_argument("--approve-all", action="store_true")
    p.add_argument("--reject-all", action="store_true")
    p.add_argument("--publish-approved", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="Build publish payloads without calling Printify")
    p.add_argument("--debug-payload-title", default="", help="Print final create_product payload for a listing title")
    p.add_argument("--export-report", action="store_true")
    args = p.parse_args()

    if args.seed_launch:
        print(f"seeded={seed_listings(True, args.collection, args.family)}")
    if args.build_assets:
        print(f"assets={build_assets_for_rows()}")
    if args.approve_all:
        print(f"approved={mark_review('APPROVED')}")
    if args.reject_all:
        print(f"rejected={mark_review('REJECTED')}")
    if args.publish_approved:
        print(f"published={publish_approved(dry_run=args.dry_run, debug_title=args.debug_payload_title)}")
    if args.export_report:
        print(f"report={dump_launch_report()}")


if __name__ == "__main__":
    main()
