#!/usr/bin/env bash
set -euo pipefail
lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
args=()
for arg in "$@"; do
  if [[ "$arg" == --wait ]]; then args+=(--wait=legacy); else args+=("$arg"); fi
done
helm upgrade --install shop "$lab_dir/shop" --kube-context kind-lab2 -n shop \
  -f "$lab_dir/shop/values.yaml" "${args[@]}"
