#!/usr/bin/env bash
set -euo pipefail
lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
helm upgrade --install shop "$lab_dir/shop" --kube-context kind-lab2 -n shop \
  -f "$lab_dir/shop/values.yaml" "$@"
