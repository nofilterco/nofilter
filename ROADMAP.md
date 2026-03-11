# Crafted Occasion Roadmap

## Phase 1 — Stabilize OS contracts (current)
- [x] Add explicit niche, template-family, personalization, launch-batch, QA policy, and diagnostics schemas.
- [x] Introduce module-oriented folders for strategy/core/template/personalization/publishing/storefront/analytics/ops.
- [x] Keep queue/publish/recheck/report flow stable while expanding architecture contracts.

## Phase 2 — Template-to-SKU compiler
- [ ] Add compiler that materializes launch listings from `(niche + template_family + product_profile + personalization_schema + policy)`.
- [ ] Emit storefront content packets, asset jobs, and publish jobs from one compile step.
- [ ] Add deterministic idempotency keys for reruns.

## Phase 3 — Storefront content system
- [ ] Generate SEO landing pages and curated collection pages from templates.
- [ ] Add PDP content blocks (benefits, personalization instructions, trust blocks, FAQ, related items).
- [ ] Add explicit indexation controls for faceted pages to prevent crawl explosion.

## Phase 4 — Personalization system hardening
- [ ] Enforce per-field validation in queue/build/publish workflows.
- [ ] Add image upload quality checks and approval routing.
- [ ] Keep UI automation as fallback only when declarative setup cannot complete.

## Phase 5 — QA confidence gate
- [ ] Score rows by design/title/niche coherence/provider readiness/mockups/SEO risk.
- [ ] Block publish below threshold and require operator override notes.
- [ ] Persist QA history in launch reports.

## Phase 6 — Analytics and learning loop
- [ ] Add analytics dimensions (niche, template_family, product_family, provider, margin target, personalization level).
- [ ] Track conversion/refund/reorder signals and compute keep/pause/expand decisions.
- [ ] Add dashboard views for underperforming combinations.

## Phase 7 — Channel expansion safely
- [ ] Preserve catalog truth while adding channel projections (Etsy first, Amazon later).
- [ ] Keep provider redundancy and risk-based routing in product profiles.
- [ ] Enforce launch gating for new product families until profile completeness reaches threshold.
