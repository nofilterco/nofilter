#!/usr/bin/env bash
set -euo pipefail

echo "== Crafted Occasion local launch test =="

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "ERROR: .env not found"
  exit 1
fi

if [[ -z "${PRINTIFY_TOKEN:-}" || -z "${PRINTIFY_SHOP_ID:-}" ]]; then
  echo "ERROR: PRINTIFY_TOKEN or PRINTIFY_SHOP_ID is missing after loading .env"
  exit 1
fi

mkdir -p local_artifacts

echo "== Backing up current state =="
cp queue.csv "local_artifacts/queue.pre_run.csv" 2>/dev/null || true
cp -R reports "local_artifacts/reports.pre_run" 2>/dev/null || true
cp catalog/product_profiles.yaml "local_artifacts/product_profiles.pre_run.yaml" 2>/dev/null || true
cp launch_report.json "local_artifacts/launch_report.pre_run.json" 2>/dev/null || true
cp launch_ops_review.csv "local_artifacts/launch_ops_review.pre_run.csv" 2>/dev/null || true
cp manual_setup_required.csv "local_artifacts/manual_setup_required.pre_run.csv" 2>/dev/null || true

echo "== Resolving Printify profiles =="
python tools/fill_printify_ids.py --write-variants --debug

echo "== Verifying resolved profiles =="
python - <<'PY'
import sys

import yaml

required = {"adult_tee_g5000", "hoodie_g18500", "mug_orca_color"}

with open("catalog/product_profiles.yaml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

bad = []
for p in data.get("product_profiles", []):
    pid = p.get("id")
    hints = p.get("printify_blueprint_hints") or {}
    meta = p.get("full_catalog_metadata") or {}
    blueprint_id = hints.get("blueprint_id", 0) or 0
    provider_id = hints.get("provider_id", 0) or 0
    matched = len(meta.get("matched_variant_ids", []) or [])
    print(f"{pid}: blueprint_id={blueprint_id} provider_id={provider_id} matched_variant_ids={matched}")
    if pid in required and (not blueprint_id or not provider_id or matched == 0):
        bad.append(pid)

if bad:
    print(f"ERROR: unresolved required profiles: {', '.join(bad)}")
    sys.exit(1)
PY

cp catalog/product_profiles.yaml "local_artifacts/product_profiles.resolved.yaml"

echo "== Clearing queue =="
rm -f queue.csv

echo "== Seeding launch =="
python run_queue.py --seed-launch --collection bridal-party
python run_queue.py --seed-launch --collection family-reunion

echo "== Building previews and setup packets =="
python run_queue.py --build-assets
python run_queue.py --setup-packets

echo "== Approving and publishing =="
python run_queue.py --approve-all
python run_queue.py --publish-approved

echo "== Rechecking sync and exporting reports =="
python run_queue.py --recheck-sync
python run_queue.py --export-report
python run_queue.py --export-manual-setup-only

echo
echo "== Done =="
echo "Review:"
echo "  launch_report.json"
echo "  launch_ops_review.csv"
echo "  manual_setup_required.csv"
