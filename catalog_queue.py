from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUEUE_PATH = Path("queue.csv")

NEW_SCHEMA = [
    "id","status","pipeline_stage","store_brand","collection_slug","collection_title","shopify_collection_tag","listing_slug","listing_title","listing_template_id","product_profile_id","product_family","publish_mode","personalization_mode","personalization_fields_json","text_fields_json","image_upload_fields_json","logo_upload_fields_json","personalization_instructions","title","seo_title","description_html","tags_csv","shopify_tags_csv","shopify_product_type","placeholder_art_mode","placeholder_art_text","printify_blueprint_id","printify_provider_id","variant_strategy","show_all_variants","in_stock_only","enabled_variant_ids_json","enabled_sizes_json","enabled_colors_json","price_cents","asset_local_path","asset_r2_url","mockup_local_path","mockup_r2_url","printify_image_id","printify_product_id","shopify_product_id","shopify_handle","shopify_sales_channel_collections","approved_at","published_at","error_stage","error_message","debug_trace","needs_manual_personalization_setup"
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
        n = {k: "" for k in NEW_SCHEMA}
        n["id"] = row.get("id") or str(i)
        n["status"] = "DRAFT"
        n["pipeline_stage"] = "LEGACY_IMPORTED"
        n["store_brand"] = "Crafted Occasion"
        n["listing_title"] = row.get("title") or f"Legacy Row {i}"
        n["title"] = row.get("title") or n["listing_title"]
        n["description_html"] = row.get("description") or ""
        n["tags_csv"] = row.get("tags") or ""
        n["debug_trace"] = "legacy-row-imported"
        migrated.append(n)
    _write(migrated)


def _write(rows: list[dict[str, Any]]) -> None:
    with QUEUE_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=NEW_SCHEMA)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in NEW_SCHEMA})


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


def dump_launch_report(path: str = "launch_report.json") -> str:
    rows = load_rows()
    payload = [{
        "collection": r["collection_slug"], "title": r["title"], "seo_title": r["seo_title"], "description_html": r["description_html"], "tags": r["tags_csv"],
        "sizes": json.loads(r["enabled_sizes_json"] or "[]"), "colors": json.loads(r["enabled_colors_json"] or "[]"),
        "profile": r["product_profile_id"], "status": r["status"], "printify_product_id": r["printify_product_id"],
        "shopify_product_id": r["shopify_product_id"], "in_stock_only": r.get("in_stock_only", ""), "show_all_variants": r.get("show_all_variants", "")
    } for r in rows]
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
