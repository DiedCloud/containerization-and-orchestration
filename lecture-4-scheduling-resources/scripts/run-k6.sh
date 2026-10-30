#!/usr/bin/env bash
set -euo pipefail
lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
phase="${1:?Usage: run-k6.sh PHASE [DURATION]}"
k6_bin="${K6_BIN:-/tmp/lab4-bin/k6-v2.3.0-linux-amd64/k6}"
mkdir -p "$lab_dir/artifacts.local"
"$k6_bin" run --quiet -e DURATION="${2:-4m}" \
  --summary-export "$lab_dir/evidence/${phase}-summary.json" \
  --out "json=$lab_dir/artifacts.local/${phase}.json" "$lab_dir/load.js" \
  > "$lab_dir/evidence/${phase}-k6.txt" 2>&1
