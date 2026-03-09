# Migration Notes: NoFilterCo -> Crafted Occasion

## Completed changes
- Added config-driven catalog system in `catalog/` with collections, profiles, templates, and 20 launch listings.
- Replaced default queue logic with listing-centric schema and migration helper (`catalog_queue.py`).
- Replaced drop/hat seeding with deterministic launch-plan seeding (`run_queue.py`).
- Replaced file-exists approval with explicit review statuses (`DRAFT`, `READY_FOR_REVIEW`, `APPROVED`, `REJECTED`, `PUBLISHED`).
- Added generalized publishing interfaces (`resolve_profile`, `resolve_variants`, `build_printify_payload`, `publish_listing`).
- Refactored UI into a catalog operations dashboard.
- Updated docs and environment defaults for Crafted Occasion.

## Manual steps still required
- Confirm final Printify blueprint/provider IDs in `catalog/product_profiles.yaml`.
- Finish Personalization Hub setup inside Printify/Shopify for personalized listings (flagged in queue).
- Validate enabled variant IDs for each provider before full-scale publish.
