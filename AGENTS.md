# Agent Operating Guidelines

This repository is a **template-first personalized commerce system** for Crafted Occasion.

## Core engineering rules
- Preserve queue safety checks and launch-status guardrails.
- Prefer declarative YAML/config updates over hidden hardcoded behavior.
- Keep manual personalization workflows operationally explicit and reportable.
- Treat Printify UI automation as a fallback path when API/declarative setup is insufficient.
- Keep channel-specific publish/sync state separate from master catalog intent.
- Do not generate SEO-spam pages or index every faceted/filter permutation.
- Do not expand product families before product profile mappings are complete (provider, blueprint, variant readiness).

## Refactor approach
- Preserve currently working publish/recheck/report flows unless a clear safety/maintainability gain exists.
- Keep changes incremental and backward compatible where possible.
- Prefer small composable modules over one large orchestration file.
