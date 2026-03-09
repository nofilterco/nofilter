# Crafted Occasion Catalog Pipeline

This repo now defaults to a **Crafted Occasion** Shopify + Printify catalog workflow for personalized gifts and apparel.

## What it does
- Seeds listings from `catalog/launch_plan.yaml` (20 launch listings).
- Stores listing-centric queue rows in `queue.csv`.
- Generates placeholder text assets (transparent PNG) for review.
- Supports review stages: `DRAFT` → `READY_FOR_REVIEW` → `APPROVED/REJECTED` → `PUBLISHED`.
- Publishes approved listings through a generalized product publisher.
- Exports launch reports for operations handoff.

## Core files
- `catalog/*.yaml` — collections, profiles, templates, launch plan
- `run_queue.py` — CLI pipeline entrypoint
- `catalog_queue.py` — queue schema + migration helper
- `catalog_assets.py` — placeholder art generation
- `publish_product.py` + `printify_catalog.py` — Printify publishing path
- `ui_app/main.py` — local dashboard

## Legacy compatibility
Legacy hat modules remain in the repo, but the default path is now catalog/listing based.
