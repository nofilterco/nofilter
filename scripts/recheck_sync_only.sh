#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

python run_queue.py --recheck-sync
python run_queue.py --export-report
python run_queue.py --export-manual-setup-only
