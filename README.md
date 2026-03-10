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
- **current launch scope**: bridal-party tees/hoodies and family-reunion tee/hoodie/mug are active; tote is excluded from seeding for now.

## Local helper scripts
- `scripts/local_launch_test.sh` — safer end-to-end local launch test: loads `.env`, verifies Printify credentials, resolves/validates required profile IDs and variants, backs up `queue.csv` + `reports/` + `catalog/product_profiles.yaml` to `local_artifacts/`, reseeds the launch collections, builds assets, generates setup packets, approves/publishes all rows, rechecks sync, and exports report/manual setup outputs.
- `scripts/recheck_sync_only.sh` — lightweight follow-up check that loads `.env`, runs `--recheck-sync`, and exports both launch and manual-setup reports.

## Publish notes
- Tee / hoodie / mug flows are active and remain default publish path.
- Tote publishing remains blocked for any legacy tote rows until profile mapping is finalized with blueprint/provider/variant IDs.

## Printify UI automation (Phase 8)
- Use `python run_queue.py --ui-automation --ui-listing-slug <slug> --dry-run --ui-screenshot-only --ui-headless` for a safe selector/screenshot pass on one listing.
- Or target a row: `python run_queue.py --ui-automation --ui-row-id <id> --dry-run --ui-headless`.
- Or scope to operational queue rows only: `python run_queue.py --ui-automation --ui-manual-required-synced-only --dry-run --ui-headless`.
- Live mode for a single product: remove `--dry-run` and `--ui-screenshot-only`.
- Artifacts are written to `out/printify_ui_automation/`:
  - run report JSON/CSV
  - before/after screenshots
  - one-time `shopify_theme_personalize_button_checklist.md` reminder for the Printify Personalize Button app block in Shopify theme editor.
- Safety controls: explicit targeting required, selector probes fail-fast, optional non-headless `--ui-confirm-each` pause before publish click.
