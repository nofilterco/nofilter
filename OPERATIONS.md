# Operations Guide

## What the system does
Crafted Occasion runs a queue-first catalog launch system for Shopify + Printify personalized products, with review controls, asset generation, publish/sync checks, and launch reporting.

## Safe launch runbook
1. Validate config/credentials:
   - `python run_queue.py --validate-config`
2. Seed a collection launch:
   - `python run_queue.py --seed-launch --collection family-reunion`
3. Build assets:
   - `python run_queue.py --build-assets`
4. Review + approve rows:
   - dashboard actions or `python run_queue.py --approve-all`
5. Publish approved:
   - `python run_queue.py --publish-approved`
6. Recheck sync and export reports:
   - `python run_queue.py --recheck-sync`
   - `python run_queue.py --setup-packets --export-manual-setup-only --export-report`

## Where manual intervention is still required
- Rows marked `needs_manual_personalization_setup=YES`.
- Products needing Shopify theme personalize button verification.
- Any failed publish/sync rows requiring operator diagnostics.

## Scaling guardrails
- Expand by template families, not ad-hoc listing duplication.
- Do not launch new product families before profile/provider/variant completeness.
- Keep faceted/filter URL generation non-indexable by default.
- Use launch batches to constrain scope and QA policy per wave.

## Existing stable workflows preserved
- Publish/recheck/report flow is unchanged.
- Queue CSV remains the operational control surface.
- UI automation remains available, but positioned as fallback.
