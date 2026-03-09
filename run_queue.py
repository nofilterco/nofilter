from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

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
            "personalization_fields_json": json.dumps(item.get("personalization_fields", [])),
            "personalization_instructions": tpl.get("personalization_instructions", "Manual personalization review may be required."),
            "title": build_title(item, tpl),
            "seo_title": build_seo_title(item, tpl),
            "description_html": build_description_html(item, tpl),
            "tags_csv": build_tags_csv(item, coll),
            "shopify_tags_csv": coll["shopify_tag"],
            "placeholder_art_mode": tpl.get("art_strategy", "text-only"),
            "placeholder_art_text": tpl.get("default_art_placeholder_text", "Custom Text"),
            "enabled_sizes_json": json.dumps(item.get("launch_visible_sizes", profile.get("launch_visible_sizes", []))),
            "enabled_colors_json": json.dumps(item.get("launch_visible_colors", profile.get("launch_visible_colors", []))),
            "price_cents": str(item.get("suggested_retail_price_cents", profile.get("retail_pricing_defaults", {}).get("default_cents", 2499))),
            "variant_strategy": "curated_launch",
            "debug_trace": f"{now_iso()}:seeded",
        })
        resolve_profile(row, profile)
        out.append(row)
    append_rows(out)
    return len(out)


def build_assets_for_rows(limit: int = 0) -> int:
    rows = load_rows()
    done = 0
    for row in rows:
        if row["status"] not in ("DRAFT", "READY_FOR_REVIEW"):
            continue
        row["asset_local_path"] = build_placeholder_asset(row.get("placeholder_art_text") or row["listing_title"], row["listing_slug"])
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


def publish_approved(limit: int = 0) -> int:
    rows = load_rows()
    count = 0
    for row in rows:
        if row["status"] != "APPROVED":
            continue
        resolve_variants(row)
        try:
            publish_listing(row)
            row["published_at"] = now_iso()
            row["pipeline_stage"] = "PUBLISHED"
        except Exception as exc:
            row["error_stage"] = "PUBLISH"
            row["error_message"] = str(exc)
        count += 1
        if limit and count >= limit:
            break
    save_rows(rows)
    return count


def main() -> None:
    p = argparse.ArgumentParser(description="Crafted Occasion catalog queue runner")
    p.add_argument("--seed-launch", action="store_true")
    p.add_argument("--collection", default="")
    p.add_argument("--family", default="")
    p.add_argument("--build-assets", action="store_true")
    p.add_argument("--approve-all", action="store_true")
    p.add_argument("--reject-all", action="store_true")
    p.add_argument("--publish-approved", action="store_true")
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
        print(f"published={publish_approved()}")
    if args.export_report:
        print(f"report={dump_launch_report()}")


if __name__ == "__main__":
    main()
