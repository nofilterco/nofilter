# Personalization System

## Principles
- Personalization is a first-class subsystem, not an afterthought.
- Field policy must be declarative and reusable across templates/products.
- Manual setup requirements must stay visible to operators.

## Config contracts
- `catalog/personalization_fields.yaml`
  - Canonical field definitions and validation constraints.
  - Includes text, date normalization, and image upload quality requirements.
- Queue rows still carry per-listing field payloads for current publish compatibility.

## Current levels
- **Level 1**: text only.
- **Level 2**: text + event/date/role fields.
- **Level 3**: text + photo upload (approval-heavy).
- **Level 4** (future): semi-custom layout choice.

## Operational behavior
- Keep `needs_manual_personalization_setup` and `MANUAL_PERSONALIZATION_REQUIRED` status as explicit safeguards.
- Use setup packets + checklist exports before live launch.
- Treat Printify UI automation as fallback when declarative setup is not enough.

## Next hardening steps
1. Enforce field regex/length in seed and publish validators.
2. Add rejection policy and unsafe-term checks.
3. Add line-wrap preview constraints in asset generation.
4. Add DPI checks for image uploads pre-publish.
