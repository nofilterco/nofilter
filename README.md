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
- **config preflight (recommended before publish/UI runs)**: `python run_queue.py --validate-config`.
- **manual personalization setup**: rows with `needs_manual_personalization_setup=YES` and `launch_status=MANUAL_PERSONALIZATION_REQUIRED` require Shopify personalization setup before launch.
- **current launch scope**: bridal-party tees/hoodies and family-reunion tee/hoodie/mug are active; tote is excluded from seeding for now.

## Real-world workflow (recommended)
1. Preflight env + credentials:
   - `python run_queue.py --validate-config`
2. Seed and build:
   - `python run_queue.py --seed-launch --collection family-reunion`
   - `python run_queue.py --build-assets`
3. Review/approve:
   - Dashboard review actions, or `python run_queue.py --approve-all`
4. Publish:
   - `python run_queue.py --publish-approved`
5. Recheck sync until stable:
   - `python run_queue.py --recheck-sync`
6. Generate setup artifacts for manual personalization and launch reporting:
   - `python run_queue.py --setup-packets --export-manual-setup-only --export-report`

### Recovery notes
- If a row fails publish with a stale/deleted `printify_product_id`, the publisher now auto-detects stale IDs and recreates the product safely.
- If you need to bulk reset stale-ID failures back to republishable rows:
  - `python run_queue.py --clear-stale-printify-ids`
  - then rerun: `python run_queue.py --retry-failed-publishes`

## Local helper scripts
- `scripts/local_launch_test.sh` — safer end-to-end local launch test: loads `.env`, verifies Printify credentials, resolves/validates required profile IDs and variants, backs up `queue.csv` + `reports/` + `catalog/product_profiles.yaml` to `local_artifacts/`, reseeds the launch collections, builds assets, generates setup packets, approves/publishes all rows, rechecks sync, and exports report/manual setup outputs.
- `scripts/recheck_sync_only.sh` — lightweight follow-up check that loads `.env`, runs `--recheck-sync`, and exports both launch and manual-setup reports.

## Publish notes
- Tee / hoodie / mug flows are active and remain default publish path.
- Tote publishing remains blocked for any legacy tote rows until profile mapping is finalized with blueprint/provider/variant IDs.

## Printify UI automation (Phase 8)
- One-time bootstrap login for Google-based auth (persistent Chrome profile):
  - `python run_queue.py --ui-automation --ui-bootstrap-login --ui-channel chrome --ui-user-data-dir local_artifacts/printify_chrome_profile`
- Normal dry-run with persistent profile:
  - `python run_queue.py --ui-automation --ui-row-id <id> --dry-run --ui-headless --ui-channel chrome --ui-user-data-dir local_artifacts/printify_chrome_profile`
- Live run with persistent profile:
  - `python run_queue.py --ui-automation --ui-row-id <id> --ui-channel chrome --ui-user-data-dir local_artifacts/printify_chrome_profile`
- You can also use `--ui-channel msedge` when Edge is preferred.
- CDP attach mode is available when you want to reuse a manually opened, already-logged-in Edge/Chrome session:
  - Start Edge (example): `msedge --remote-debugging-port=9222 --user-data-dir=/tmp/printify-edge-cdp-profile`
  - Log into Printify manually in that browser window.
  - Dry-run attach: `python run_queue.py --ui-automation --ui-row-id <id> --dry-run --ui-cdp-url http://localhost:9222`
  - Live attach: `python run_queue.py --ui-automation --ui-row-id <id> --ui-cdp-url http://localhost:9222`
- Legacy state-file flow is still available via `--ui-storage-state`, but persistent profiles/CDP attach are recommended for Google sign-in reliability.
- Targeting supports both queue-backed and direct modes:
  - Queue-backed: `--ui-row-id`, `--ui-listing-slug`, or `--ui-manual-required-synced-only`
  - Direct: `--ui-product-url` or `--ui-printify-product-id` (optionally pair with `--ui-row-id`/`--ui-listing-slug` to inherit queue/checklist/setup-packet metadata and override only product ID).
- Direct mode with no matched queue row defaults to safe publish prerequisites:
  - `--ui-variant-visibility in_stock_only` (default)
  - Sync details default to `product_title,description,mockups,colors_sizes_prices_skus,tags,shipping_profile`
  - Optional overrides: `--ui-enable-personalization`, `--ui-variant-visibility`, `--ui-sync-details`, `--ui-title`.
- Dry-run still performs no publish click; `--ui-screenshot-only` remains non-clicking selector/screenshot probing.
- Artifacts are written to `out/printify_ui_automation/`:
  - run report JSON/CSV
  - before/after screenshots
  - one-time `shopify_theme_personalize_button_checklist.md` reminder for the Printify Personalize Button app block in Shopify theme editor.
- Safety controls: selector probes fail-fast, optional non-headless `--ui-confirm-each` pause before publish click.
- Publishing settings robustness: the UI automation now explicitly re-opens/activates the Publishing settings section before variant visibility, sync detail checks, and publish-button probing, with per-attempt control diagnostics recorded in the report.
