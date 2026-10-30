#!/usr/bin/env bash
set -euo pipefail
platform_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
lab_dir="$(dirname "$platform_dir")"
kube_context="${KUBE_CONTEXT:-kind-lab2}"
bash "$platform_dir/install-monitoring-crds.sh"
helm upgrade shop "$lab_dir/shop" --kube-context "$kube_context" -n shop \
  -f "$lab_dir/shop/values.yaml" --wait --timeout 3m
python3 "$lab_dir/scripts/sync-monitoring.py" --context "$kube_context"
