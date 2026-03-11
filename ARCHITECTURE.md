# Crafted Occasion Personalized Commerce OS Architecture

## Brief audit summary (pre-refactor)

What is already solid:
- Queue-first launch flow with status normalization and publish/sync recheck lifecycle.
- Config-driven catalog primitives (`collections`, `listing_templates`, `product_profiles`, `launch_plan`).
- Operational reporting and manual-review/personalization guardrails.
- Printify UI automation with dry-run, diagnostics artifacts, and safety probes.

What was fragile:
- Strategy, merchandising, and execution were mixed in `catalog/launch_plan.yaml`.
- Launch planning was listing-centric instead of template/niche-centric.
- Source catalog intent and channel publish state were not explicitly modeled as separate architecture layers.
- Personalization rules existed on rows/templates, but did not have a centralized field-policy schema.

What was missing for scale:
- Formal niche strategy model.
- Reusable template-family model with constraints and SEO/content rules.
- Batch-level launch orchestration config.
- QA scoring policy model and diagnostics taxonomy for publish confidence.

---

## New architecture model

The project now follows a **Personalized Commerce OS** mental model with explicit modules:

1. `brand_strategy/` — niche/intent strategy.
2. `catalog_core/` — canonical catalog data contracts and orchestration glue.
3. `template_engine/` — reusable design template families.
4. `product_profiles/` — profile/provider/variant readiness and constraints.
5. `personalization/` — field definitions and customer input guardrails.
6. `publishing/` — Printify/Shopify projection and sync diagnostics.
7. `storefront/` — landing-page/PDP content generation strategy.
8. `analytics/` — performance dimensions and learning-loop schema.
9. `ops/` — operator workflows, launch controls, and governance.

## Data layer split

- **Catalog truth (master intent)**
  - Niche strategy (`catalog/niches.yaml`)
  - Template families (`catalog/template_families.yaml`)
  - Product profiles (`catalog/product_profiles.yaml`)
  - Personalization field policies (`catalog/personalization_fields.yaml`)
  - Launch batch metadata (`catalog/launch_batches.yaml`)
  - QA gates (`catalog/qa_scoring.yaml`)

- **Launch projection (generated execution)**
  - Listing rows seeded into `queue.csv`.
  - Build assets, review states, publish attempts.

- **Channel state (runtime/publish state)**
  - Printify publish status / IDs.
  - Shopify sync state and diagnostics history.
  - Manual personalization setup status.

## Backward compatibility

`run_queue.py` seeding remains operational and backward compatible:
- `catalog/launch_plan.yaml` remains the execution row source.
- `catalog_config.load_catalog()` now loads expanded OS-level schemas while still exposing launch rows.
- Existing publish/recheck/report behavior remains unchanged.
