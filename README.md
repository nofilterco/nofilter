# Crafted Occasion Catalog Pipeline

This repo runs the **Crafted Occasion** Shopify + Printify catalog workflow for personalized apparel and gift products.

## What it does
- Seeds listings from `catalog/launch_plan.yaml` into queue-first records.
- Builds styled placeholder assets using collection style packs and layout strategies.
- Carries rich buyer-facing personalization metadata and separate internal workflow metadata.
- Tracks explicit stock and variant flags (`in_stock_only`, `show_all_variants`) per queue row.
- Uses review/publish statuses including Printify/Shopify sync and failure states.
- Publishes approved listings through the generalized Printify publisher.
- Records publish/sync diagnostics and per-row publish log history.
- Exports launch report JSON and ops-focused CSV.

## Core files
- `catalog/*.yaml` — collections, profiles, templates, launch plan
- `run_queue.py` — CLI entrypoint for seed/build/review/publish/recheck/export
- `catalog_queue.py` — queue schema + migration + report exports
- `catalog_assets.py` — styled placeholder art engine
- `publish_product.py` + `printify_catalog.py` — publish + sync checks
- `ui_app/main.py` — local dashboard API

## Launch Ops
- **seed**: `python run_queue.py --seed-launch --collection family-reunion` (or `bridal-party`).
- **build**: `python run_queue.py --build-assets`.
- **review**: use dashboard row actions for approve/reject or CLI `--approve-all` / `--reject-all`.
- **publish**: `python run_queue.py --publish-approved`.
- **recheck sync**: `python run_queue.py --recheck-sync`.
- **manual personalization setup**: rows with `needs_manual_personalization_setup=YES` and `launch_status=MANUAL_PERSONALIZATION_REQUIRED` require Shopify personalization setup before launch.
- **tote blocking behavior**: tote rows remain blocked in publisher until blueprint/provider/variant mapping is finalized.

## Publish notes
- Tee / hoodie / mug flows are active and remain default publish path.
- Tote publishing is intentionally blocked until profile mapping is finalized with blueprint/provider/variant IDs.
