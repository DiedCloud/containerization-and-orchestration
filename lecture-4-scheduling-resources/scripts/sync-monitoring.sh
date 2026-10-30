#!/usr/bin/env bash
# Reuse the CRD -> existing Lab 2 release adapter from Lab 3.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$repo_dir/lecture-3-kubernetes-control-plane/scripts/sync-monitoring.py" \
  --context kind-lab2 --output "$repo_dir/lecture-4-scheduling-resources/artifacts.local/monitoring"
