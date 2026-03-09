# Crafted Occasion Catalog Pipeline

This repo runs the **Crafted Occasion** Shopify + Printify catalog workflow for personalized apparel and gift products.

## What it does
- Seeds listings from `catalog/launch_plan.yaml` into queue-first records.
- Builds styled placeholder assets using collection style packs and layout strategies (not just centered text).
- Carries richer template metadata (text/photo/logo upload field definitions and buyer-facing labels).
- Tracks explicit stock and variant flags (`in_stock_only`, `show_all_variants`) per queue row.
- Uses review stages: `DRAFT` → `READY_FOR_REVIEW` → `APPROVED/REJECTED` → `PUBLISHED`.
- Publishes approved listings through the generalized Printify publisher.
- Records publish/sync diagnostics (`printify_publish_status`, `shopify_sync_status`, `last_publish_response`, `last_sync_check_at`).
- Exports launch reports for operations QA and merchandising handoff.

## Core files
- `catalog/*.yaml` — collections, profiles, templates, launch plan
- `run_queue.py` — CLI entrypoint for seed/build/review/publish/export
- `catalog_queue.py` — queue schema + migration helper
- `catalog_assets.py` — styled placeholder art engine
- `catalog_builders.py` — title/SEO/description/tag builders
- `publish_product.py` + `printify_catalog.py` — publish + sync checks
- `ui_app/main.py` — local dashboard

## Publish notes
- Tee / hoodie / mug flows are active and should remain the default publish path.
- Tote publishing is intentionally blocked until profile mapping is finalized with blueprint/provider/variant IDs.

## Legacy compatibility
Legacy hat modules remain in the repo, but the default path is catalog/listing based.
